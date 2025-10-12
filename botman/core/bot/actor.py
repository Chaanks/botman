import asyncio
import logging
import traceback
import time
from typing import Optional, Dict, Any
from functools import singledispatchmethod

from botman.core.actor import Actor
from botman.core.api import ArtifactsClient
from botman.core.api.models import Character, Skill, CharacterRole
from botman.core.tasks import Task, TaskContext, DepositTask, GatherTask, FightTask
from botman.core.world import World
from botman.core.errors import (
    FatalError,
    RecoverableError,
    RetriableError,
    APIError,
    CODE_CHARACTER_INVENTORY_FULL,
    CODE_BANK_FULL,
)
from botman.core.mrp.messages import (
    QueryJobsRequest,
    QueryJobsResponse,
    ClaimJobRequest,
    ClaimJobResponse,
    CompleteJobRequest,
    CompleteJobResponse,
)
from botman.core.bot.messages import (
    TaskCreateMessage,
    StatusRequestMessage,
    GetStatusMessage,
    GetStatusResponse,
)
from botman.web.bridge.messages import (
    BotChangedMessage,
    LogMessage,
)


class Bot(Actor):
    def __init__(
        self,
        name: str,
        token: str,
        ui: Actor,
        world: World,
        role: CharacterRole,
        skills: list[Skill],
        bank: Actor,
        orchestrator: Optional[Actor] = None,
        inbox_size: int = 50,
    ):
        super().__init__(name=name, inbox_size=inbox_size)
        # Note: self.name is now set by Actor.__init__, no need to set it again
        self.token = token
        self.ui = ui
        self.world = world
        self.role: CharacterRole = role
        self.skills: list[Skill] = skills
        self.bank: Actor = bank
        self.orchestrator: Optional[Actor] = orchestrator
        self.api: Optional[ArtifactsClient] = None
        self.character: Optional[Character] = None

        self.current_task: Optional[Task] = None
        self.task_queue: list[Task] = []
        self.execution_task: Optional[asyncio.Task] = None

        # Job tracking
        self.current_job_id: Optional[str] = None

        self.logger = logging.getLogger(f"botman.bot.{name}")
        self._last_published_state: Optional[Dict[str, Any]] = None

    async def on_start(self):
        self.logger.info(f"Bot {self.name} starting...")
        self.api = ArtifactsClient(self.token)
        try:
            self.character = await self.api.get_character(self.name)
            await self._log(f"Initialized (Lvl {self.character.level})")
            await self._publish_status(force=True)
            self.execution_task = asyncio.create_task(self._execution_loop())
        except APIError as e:
            await self._log(f"Fatal error during initialization: {e}", level="CRITICAL")
            self.logger.error(f"Initialization failed:\n{traceback.format_exc()}")
            # If init fails, we can't continue.
            # TODO: notify a supervisor.
            await self.stop()
        except Exception as e:
            await self._log(
                f"An unexpected error occurred during startup: {e}", level="CRITICAL"
            )
            self.logger.error(
                f"Unexpected initialization error:\n{traceback.format_exc()}"
            )
            raise

    async def on_stop(self):
        self.logger.info(f"Bot {self.name} stopping...")
        if self.execution_task:
            self.execution_task.cancel()
            try:
                await self.execution_task
            except asyncio.CancelledError:
                pass
        if self.api:
            await self.api.close()

    @singledispatchmethod
    async def on_receive(self, message) -> Any:
        """
        Handle incoming typed messages using singledispatch.

        All messages must be dataclass instances for type safety.
        """
        self.logger.warning(f"Unknown message type: {type(message)}")
        return None

    @on_receive.register
    async def _(self, msg: TaskCreateMessage) -> None:
        """Handle task creation request."""
        self.task_queue.append(msg.task)
        await self._log(f"Task queued: {msg.task.description()}")
        await self._publish_status()
        return None

    @on_receive.register
    async def _(self, msg: StatusRequestMessage) -> None:
        """Handle status publication request."""
        await self._publish_status()
        return None

    @on_receive.register
    async def _(self, msg: GetStatusMessage) -> GetStatusResponse:
        """Handle status query request."""
        return GetStatusResponse(
            name=self.name,
            status=self._get_status(),
            current_task=self.current_task.description() if self.current_task else None,
            cooldown=int(self.character.ready_in()) if self.character else 0,
        )

    async def _execution_loop(self):
        while self._running:
            try:
                if not self.character.can_act():
                    await self._publish_status()
                    await asyncio.sleep(0.5)
                    continue

                # Priority 1: Execute current task
                if not self.current_task and self.task_queue:
                    self.current_task = self.task_queue.pop(0)
                    await self._log(f"Starting task: {self.current_task.description()}")

                # Priority 2: If no task, poll job board
                if not self.current_task and not self.task_queue and self.orchestrator:
                    await self._poll_and_claim_job()

                # Priority 3: If still idle, perform default role-based behavior
                if not self.current_task and not self.task_queue:
                    await self._perform_idle_behavior()

                if self.current_task:
                    context = TaskContext(
                        self.character, self.api, self.world, self.bank
                    )
                    result = await self.current_task.execute(context)

                    # Update character state from result if available
                    if result.character:
                        self.character = result.character

                    # Log any messages from the task
                    if result.log_messages:
                        for message, level in result.log_messages:
                            await self._log(message, level=level)

                    if result.error:
                        error = result.error
                        if isinstance(error, FatalError):
                            await self._log(
                                f"Fatal error, stopping bot: {error}", "CRITICAL"
                            )
                            self._running = False
                            continue
                        elif isinstance(error, RecoverableError):
                            await self._log(
                                f"Task paused for recovery: {error}", "WARNING"
                            )
                            await self._handle_recovery(self.current_task, error)
                            self.current_task = None
                        elif isinstance(error, RetriableError):
                            await self._log(
                                f"Retriable error: {error}. Waiting for cooldown.",
                                "INFO",
                            )
                            # Do NOT clear current_task, so it runs again after cooldown
                        else:
                            await self._log(f"Task failed: {error}", "ERROR")
                            self.current_task = None
                    elif result.completed:
                        await self._log(
                            f"Task completed: {self.current_task.description()}"
                        )
                        self.current_task = None

                        # If we just completed a job, check if all job tasks are done
                        # A job is complete when: we have a current_job_id AND the task queue is empty
                        if (
                            self.current_job_id
                            and self.orchestrator
                            and not self.task_queue
                        ):
                            await self._complete_job()

                await self._publish_status()
                await asyncio.sleep(0.1)  # TODO tweak this

            except asyncio.CancelledError:
                self.logger.info(f"Execution loop cancelled for {self.name}")
                break
            except Exception:
                await self._log(
                    "An unexpected exception occurred in the execution loop!",
                    "CRITICAL",
                )
                self.logger.error(f"Execution loop error:\n{traceback.format_exc()}")
                self.current_task = None

    async def _handle_recovery(self, paused_task: Task, error: RecoverableError):
        """Handles a recoverable error by queueing a corrective task."""
        from botman.core.tasks.craft import CraftTask

        if error.code == CODE_CHARACTER_INVENTORY_FULL:
            craft_tasks = []

            for inv_item in self.character.inventory:
                # Check if the item has a single recipe
                recipe_item = self.world.single_recipe_from_gather(inv_item.code)

                if recipe_item:
                    # Calculate how many we can craft
                    material_qty_needed = 1
                    if recipe_item.craft:
                        for requirement in recipe_item.craft.requirements:
                            if requirement.code == inv_item.code:
                                material_qty_needed = requirement.quantity
                                break

                    max_crafts = inv_item.quantity // material_qty_needed
                    if max_crafts > 0:
                        craft_tasks.append(
                            (
                                CraftTask(
                                    item_code=recipe_item.code, target_amount=max_crafts
                                ),
                                inv_item.code,
                                inv_item.quantity,
                                recipe_item.code,
                                max_crafts,
                            )
                        )

            self.task_queue.insert(0, paused_task)

            deposit_task = DepositTask(deposit_all=True)
            self.task_queue.insert(0, deposit_task)

            if craft_tasks:
                craft_descriptions = []
                for (
                    craft_task,
                    material_code,
                    material_qty,
                    craft_item,
                    max_crafts,
                ) in reversed(craft_tasks):
                    self.task_queue.insert(0, craft_task)
                    craft_descriptions.append(
                        f"{material_code} x{material_qty} → {craft_item} x{max_crafts}"
                    )

                await self._log(
                    f"Inventory full: will craft {', '.join(craft_descriptions)}, then deposit and resume",
                    "INFO",
                )
            else:
                await self._log("Inventory full: will deposit and resume", "INFO")

        elif error.code == CODE_BANK_FULL:
            await self._log("Bank is full. No recovery task defined.", "ERROR")
        else:
            await self._log(
                f"Unknown recoverable error code {error.code}. Cannot auto-recover.",
                "ERROR",
            )

    def _get_status(self) -> str:
        if self.current_task:
            return "Busy"
        elif not self.character.can_act():
            return "Cooldown"
        elif self.task_queue:
            return "Ready"
        else:
            return "Idle"

    async def _publish_status(self, force: bool = False):
        bot_data = {
            "status": self._get_status(),
            "current_task": self.current_task.description()
            if self.current_task
            else None,
            "progress": self.current_task.progress() if self.current_task else "0/0",
            "cooldown": int(self.character.ready_in()) if self.character else 0,
            "character": self.character,
            "queue_size": len(self.task_queue),
        }

        # Only publish if state changed (excluding character object which always differs)
        state_key = (
            bot_data["status"],
            bot_data["current_task"],
            bot_data["progress"],
            bot_data["queue_size"],
            bot_data["cooldown"],
        )

        if force or self._last_published_state != state_key:
            self._last_published_state = state_key
            await self.ui.tell(BotChangedMessage(bot_name=self.name, data=bot_data))

    async def _log(self, message: str, level: str = "INFO"):
        # Send to UI
        await self.ui.tell(
            LogMessage(
                level=level,
                source=self.name,
                message=message,
                timestamp=time.time(),
            )
        )

        # Also log to file
        log_func = getattr(self.logger, level.lower(), self.logger.info)
        log_func(f"[{self.name}] {message}")

    # Idle Behavior System
    def _get_skill_level(self, skill: Skill) -> int:
        """Get current level for a skill from character data."""
        if not self.character or not self.character.skills:
            return 1

        skill_data = getattr(self.character.skills, skill.value, None)
        if skill_data:
            return skill_data.level
        return 1

    async def _perform_idle_behavior(self) -> None:
        """Default behavior based on role and skills when no jobs available."""

        # GATHERER: Gather highest level resource for primary skill
        if self.role == CharacterRole.GATHERER and self.skills:
            primary_skill = self.skills[0]
            skill_level = self._get_skill_level(primary_skill)
            resource = self.world.highest_gathering_resource(primary_skill, skill_level)

            if resource:
                task = GatherTask(resource_code=resource.code, target_amount=100)
                self.task_queue.append(task)
                self.task_queue.append(DepositTask(deposit_all=True))
                await self._log(f"Idle: gathering {resource.code}")
                return

        # FIGHTER: Fight monsters around your level
        elif self.role == CharacterRole.FIGHTER:
            monster = "chicken"
            task = FightTask(monster_code=monster, target_kills=100)
            self.task_queue.append(task)
            self.task_queue.append(DepositTask(deposit_all=True))
            await self._log(f"Idle: fighting {monster}")
            return

        # CRAFTER: Level up primary crafting skill
        elif self.role == CharacterRole.CRAFTER and self.skills:
            resource = "ash_tree"
            task = GatherTask(resource_code=resource, target_amount=100)
            self.task_queue.append(task)
            self.task_queue.append(DepositTask(deposit_all=True))
            await self._log(f"Idle: gathering {resource}")
            return

        # SUPPORT: Gather resources for consumables (fishing/cooking/alchemy)
        elif self.role == CharacterRole.SUPPORT and self.skills:
            primary_skill = self.skills[0]
            skill_level = self._get_skill_level(primary_skill)

            # Support roles gather like gatherers
            if primary_skill in {Skill.FISHING, Skill.MINING, Skill.ALCHEMY}:
                resource = self.world.highest_gathering_resource(primary_skill, skill_level)

                if resource:
                    task = GatherTask(resource_code=resource.code, target_amount=100)
                    self.task_queue.append(task)
                    self.task_queue.append(DepositTask(deposit_all=True))
                    await self._log(f"Idle: gathering {resource.code}")
                    return

    # MRP Job System
    async def _poll_and_claim_job(self) -> None:
        """Poll the job board for suitable jobs and claim one if available."""
        if not self.orchestrator:
            return

        try:
            query = QueryJobsRequest(role=self.role, skills=self.skills)
            response: QueryJobsResponse = await self.orchestrator.ask(query)

            if not response.jobs:
                return

            job = response.jobs[0]
            self.logger.info(
                f"Found suitable job: {job.id} - {job.type.value} {job.item_code} x{job.quantity}"
            )

            claim = ClaimJobRequest(job_id=job.id, bot_name=self.name)
            claim_response: ClaimJobResponse = await self.orchestrator.ask(claim)

            if claim_response.success:
                self.current_job_id = job.id
                await self._log(
                    f"Claimed job: {job.type.value} {job.item_code} x{job.quantity}"
                )

                try:
                    tasks = job.to_tasks(self.world)
                    self.task_queue.extend(tasks)
                    await self._log(f"Added {len(tasks)} tasks to queue")
                except Exception as e:
                    await self._log(f"Failed to create tasks from job: {e}", "ERROR")
                    self.current_job_id = None
            else:
                self.logger.debug(f"Failed to claim job {job.id}: {claim_response.error}")

        except Exception as e:
            self.logger.error(f"Error polling job board: {e}", exc_info=True)

    async def _complete_job(self) -> None:
        """Notify orchestrator that the current job is complete."""
        if not self.current_job_id or not self.orchestrator:
            return

        try:
            request = CompleteJobRequest(job_id=self.current_job_id, bot_name=self.name)
            response: CompleteJobResponse = await self.orchestrator.ask(request)

            if response.success:
                if response.plan_complete:
                    await self._log("Production plan complete!", "INFO")
                self.current_job_id = None
            else:
                self.logger.error(f"Failed to complete job: {response.error}")

        except Exception as e:
            self.logger.error(f"Error completing job: {e}")
