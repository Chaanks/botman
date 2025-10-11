import asyncio
import logging
import traceback
import time
from typing import Optional, Dict, Any

from botman.core.actor import Actor
from botman.core.api import ArtifactsClient
from botman.core.models import Character
from botman.core.tasks import Task, TaskContext
from botman.core.world import World
from botman.core.errors import (
    FatalError,
    RecoverableError,
    RetriableError,
    APIError,
    CODE_CHARACTER_INVENTORY_FULL,
    CODE_BANK_FULL
)


class BotActor(Actor):
    def __init__(self, name: str, token: str, ui: Actor, world: World):
        super().__init__()
        self.name = name
        self.token = token
        self.ui = ui
        self.world = world
        self.character: Optional[Character] = None
        self.api: Optional[ArtifactsClient] = None
        self.current_task: Optional[Task] = None
        self.task_queue: list[Task] = []
        self.execution_task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger(f"botman.bot.{name}")

    async def on_start(self):
        self.logger.info(f"Bot {self.name} starting...")
        self.api = ArtifactsClient(self.token)
        try:
            self.character = await self.api.get_character(self.name)
            await self._log(f"Initialized (Lvl {self.character.level})")
            await self._publish_status()
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
        self.task_queue.insert(0, paused_task)
        await self._log(f"Re-queued task '{paused_task.description()}' to run after recovery.")

        # This is where you would create and queue a specific recovery task.
        # For example, if a `DepositAllTask` exists:
        # recovery_task = DepositAllTask()
        # self.task_queue.insert(0, recovery_task)
        # await self._log(f"Queued recovery task: {recovery_task.description()}")

        if error.code == CODE_CHARACTER_INVENTORY_FULL:
            await self._log("Inventory full. A recovery task (e.g., DepositAllTask) should be queued here.", "WARNING")
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

    async def _publish_status(self):
        bot_data = {
            'status': self._get_status(),
            'current_task': self.current_task.description() if self.current_task else None,
            'progress': self.current_task.progress() if self.current_task else "0/0",
            'cooldown': int(self.character.ready_in()) if self.character else 0,
            'character': self.character,
            'queue_size': len(self.task_queue),
        }
        await self.ui.tell({'type': 'bot_changed', 'bot_name': self.name, 'data': bot_data})

    async def _log(self, message: str, level: str = "INFO"):
        await self.ui.tell({
            'type': 'log',
            'level': level,
            'source': self.name,
            'message': message,
            'timestamp': time.time(),
        })
