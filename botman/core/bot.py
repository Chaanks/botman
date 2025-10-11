import asyncio
from enum import Enum
import logging
import traceback
import time
from typing import Optional, Dict, Any

from botman.core.actor import Actor
from botman.core.api import ArtifactsClient
from botman.core.models import Character, Skill
from botman.core.tasks import Task, TaskContext, DepositTask
from botman.core.world import World
from botman.core.errors import (
    FatalError,
    RecoverableError,
    RetriableError,
    APIError,
    CODE_CHARACTER_INVENTORY_FULL,
    CODE_BANK_FULL
)

class BotRole(str, Enum):
    GATHERER = "gatherer"
    FIGHTER = "fighter"
    CRAFTER = "crafter"
    SUPPORT = "support"

class Bot(Actor):
    def __init__(self, name: str, token: str, ui: Actor, world: World, role: BotRole, skills: list[Skill]):
        super().__init__()
        self.name = name
        self.token = token
        self.ui = ui
        self.world = world
        self.role: BotRole = role
        self.skills: list[Skill] = skills
        self.api: Optional[ArtifactsClient] = None
        self.character: Optional[Character] = None

        self.current_task: Optional[Task] = None
        self.task_queue: list[Task] = []
        self.execution_task: Optional[asyncio.Task] = None

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
            await self._log(f"An unexpected error occurred during startup: {e}", level="CRITICAL")
            self.logger.error(f"Unexpected initialization error:\n{traceback.format_exc()}")
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

    async def on_receive(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg_type = message.get('type')

        if msg_type == 'task_create':
            task = message.get('task')
            if task:
                self.task_queue.append(task)
                await self._log(f"Task queued: {task.description()}")
                await self._publish_status()
            return None
        elif msg_type == 'status_request':
            await self._publish_status()
            return None
        elif msg_type == 'get_status':
            return {
                'name': self.name,
                'status': self._get_status(),
                'current_task': self.current_task.description() if self.current_task else None,
                'cooldown': int(self.character.ready_in()) if self.character else 0,
            }
        else:
            self.logger.warning(f"Unknown message type: {msg_type}")
            return None

    async def _execution_loop(self):
        while self._running:
            try:
                if not self.character.can_act():
                    await self._publish_status()
                    await asyncio.sleep(0.5)
                    continue

                if not self.current_task and self.task_queue:
                    self.current_task = self.task_queue.pop(0)
                    await self._log(f"Starting task: {self.current_task.description()}")

                if self.current_task:
                    context = TaskContext(self.character, self.api, self.world)
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
                            await self._log(f"Fatal error, stopping bot: {error}", "CRITICAL")
                            self._running = False
                            continue
                        elif isinstance(error, RecoverableError):
                            await self._log(f"Task paused for recovery: {error}", "WARNING")
                            await self._handle_recovery(self.current_task, error)
                            self.current_task = None
                        elif isinstance(error, RetriableError):
                            await self._log(f"Retriable error: {error}. Waiting for cooldown.", "INFO")
                            # Do NOT clear current_task, so it runs again after cooldown
                        else:
                            await self._log(f"Task failed: {error}", "ERROR")
                            self.current_task = None
                    elif result.completed:
                        await self._log(f"Task completed: {self.current_task.description()}")
                        self.current_task = None

                await self._publish_status()
                await asyncio.sleep(0.1) # TODO tweak this

            except asyncio.CancelledError:
                self.logger.info(f"Execution loop cancelled for {self.name}")
                break
            except Exception:
                await self._log("An unexpected exception occurred in the execution loop!", "CRITICAL")
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
                        craft_tasks.append((
                            CraftTask(item_code=recipe_item.code, target_amount=max_crafts),
                            inv_item.code,
                            inv_item.quantity,
                            recipe_item.code,
                            max_crafts
                        ))

            self.task_queue.insert(0, paused_task)

            deposit_task = DepositTask(deposit_all=True)
            self.task_queue.insert(0, deposit_task)

            if craft_tasks:
                craft_descriptions = []
                for craft_task, material_code, material_qty, craft_item, max_crafts in reversed(craft_tasks):
                    self.task_queue.insert(0, craft_task)
                    craft_descriptions.append(f"{material_code} x{material_qty} → {craft_item} x{max_crafts}")

                await self._log(
                    f"Inventory full: will craft {', '.join(craft_descriptions)}, then deposit and resume",
                    "INFO"
                )
            else:
                await self._log(f"Inventory full: will deposit and resume", "INFO")

        elif error.code == CODE_BANK_FULL:
            await self._log(f"Bank is full. No recovery task defined.", "ERROR")
        else:
            await self._log(f"Unknown recoverable error code {error.code}. Cannot auto-recover.", "ERROR")

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
            'status': self._get_status(),
            'current_task': self.current_task.description() if self.current_task else None,
            'progress': self.current_task.progress() if self.current_task else "0/0",
            'cooldown': int(self.character.ready_in()) if self.character else 0,
            'character': self.character,
            'queue_size': len(self.task_queue),
        }

        # Only publish if state changed (excluding character object which always differs)
        state_key = (bot_data['status'], bot_data['current_task'], bot_data['progress'], bot_data['queue_size'])

        if force or self._last_published_state != state_key:
            self._last_published_state = state_key
            await self.ui.tell({'type': 'bot_changed', 'bot_name': self.name, 'data': bot_data})

    async def _log(self, message: str, level: str = "INFO"):
        # Send to UI
        await self.ui.tell({
            'type': 'log',
            'level': level,
            'source': self.name,
            'message': message,
            'timestamp': time.time(),
        })

        # Also log to file
        log_func = getattr(self.logger, level.lower(), self.logger.info)
        log_func(f"[{self.name}] {message}")
