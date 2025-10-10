"""
Async Bot Actor - converts Pykka-based bot to async Actor.
"""

import asyncio
import logging
import traceback
import time
from typing import Optional, Dict, Any

from actor import Actor
from api import ArtifactsClient
from models import Character
from tasks import TaskContext
from world import World
from errors import CODE_CHARACTER_INVENTORY_FULL


class BotActor(Actor):
    """Async Bot Actor for managing game characters."""

    def __init__(
        self,
        name: str,
        token: str,
        ui: Actor,
        world: World,
    ):
        super().__init__()
        self.name = name
        self.token = token
        self.ui = ui
        self.world = world

        # Bot state
        self.character: Optional[Character] = None
        self.api: Optional[ArtifactsClient] = None
        self.current_task = None
        self.task_queue = []

        # Execution loop task
        self.execution_task: Optional[asyncio.Task] = None

        # Logger
        self.logger = logging.getLogger(f"botman.bot.{name}")

    async def on_start(self):
        """Initialize bot and start execution loop."""
        self.logger.info(f"Bot {self.name} starting...")

        # Create API client
        self.api = ArtifactsClient(self.token)

        try:
            # Fetch character data
            self.character = await self.api.get_character(self.name)
            await self._log(f"Initialized (Lvl {self.character.level})")
            await self._publish_status()

            # Start execution loop
            self.execution_task = asyncio.create_task(self._execution_loop())

        except Exception as e:
            error_msg = f"Failed to initialize: {e}"
            await self._log(error_msg, level="ERROR")
            self.logger.error(f"Initialization error:\n{traceback.format_exc()}")
            raise

    async def on_stop(self):
        """Cleanup bot resources."""
        self.logger.info(f"Bot {self.name} stopping...")

        # Cancel execution loop
        if self.execution_task:
            self.execution_task.cancel()
            try:
                await self.execution_task
            except asyncio.CancelledError:
                pass

        # Close API client
        if self.api:
            await self.api.close()

    async def on_receive(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle incoming messages."""
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
            # Return current status synchronously
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
        """Main execution loop for processing tasks."""
        try:
            while self._running:
                # Check if character can act
                if not self.character.can_act():
                    await self._publish_status()
                    await asyncio.sleep(0.5)
                    continue

                # Start next task if idle and ready
                if not self.current_task and self.task_queue:
                    self.current_task = self.task_queue.pop(0)
                    await self._log(f"Starting task: {self.current_task.description()}")
                    await self._publish_status()

                # Execute current task
                if self.current_task:
                    try:
                        # Create context for task execution
                        context = TaskContext(
                            character=self.character,
                            api=self.api,
                            world=self.world
                        )

                        # Execute task
                        result = await self.current_task.execute(context)

                        # Process log messages
                        if result.log_messages:
                            for message, level in result.log_messages:
                                await self._log(message, level=level)

                        # Update character state
                        if result.character:
                            self.character = result.character

                        # Handle task result
                        if result.completed:
                            await self._log(
                                f"Task completed: {self.current_task.description()}"
                            )
                            self.current_task = None

                        elif result.paused:
                            # Autonomous recovery
                            await self._handle_paused_task(self.current_task, result)
                            self.current_task = None

                        elif result.error:
                            # Task failed
                            await self._log(f"Task failed: {result.error}", level="ERROR")
                            self.current_task = None

                        await self._publish_status()

                    except Exception as e:
                        error_msg = f"Task execution exception: {e}"
                        await self._log(error_msg, level="ERROR")
                        self.logger.error(
                            f"Task execution exception for task '{self.current_task.description()}':\n"
                            f"{traceback.format_exc()}"
                        )
                        self.current_task = None
                        await self._publish_status()

                await asyncio.sleep(0.01)

        except asyncio.CancelledError:
            self.logger.info(f"Execution loop cancelled for {self.name}")
            raise

        except Exception as e:
            error_msg = f"Execution loop error: {e}"
            await self._log(error_msg, level="ERROR")
            self.logger.error(f"Execution loop error:\n{traceback.format_exc()}")

    async def _handle_paused_task(self, task, result):
        """Handle paused task with autonomous recovery."""
        error_code = self._extract_error_code(result.error)

        if error_code == CODE_CHARACTER_INVENTORY_FULL:
            await self._log(
                "Inventory full - need to implement DepositAllTask for recovery",
                level="WARNING",
            )
        else:
            await self._log(
                f"Task paused with unknown error code {error_code}, cannot auto-recover",
                level="WARNING",
            )

    def _extract_error_code(self, error_str):
        """Extract error code from error string like '[497] Message'."""
        if not error_str:
            return None
        try:
            start = error_str.find("[")
            end = error_str.find("]")
            if start != -1 and end != -1:
                return int(error_str[start + 1 : end])
        except (ValueError, IndexError):
            pass
        return None

    def _get_status(self) -> str:
        """Calculate current status based on character state."""
        if self.current_task:
            return "Busy"
        elif not self.character.can_act():
            return "Cooldown"
        elif self.task_queue:
            return "Ready"
        else:
            return "Idle"

    async def _publish_status(self):
        """Publish status to UI via UIBridge."""
        bot_data = {
            'status': self._get_status(),
            'current_task': self.current_task.description() if self.current_task else None,
            'progress': self.current_task.progress() if self.current_task else "0/0",
            'cooldown': int(self.character.ready_in()) if self.character else 0,
            'character': self.character,
            'queue_size': len(self.task_queue),
        }

        await self.ui.tell({
            'type': 'bot_changed',
            'bot_name': self.name,
            'data': bot_data
        })

    async def _log(self, message: str, level: str = "INFO"):
        """Send log message to UIBridge."""
        await self.ui.tell({
            'type': 'log',
            'level': level,
            'source': self.name,
            'message': message,
            'timestamp': time.time(),
        })
