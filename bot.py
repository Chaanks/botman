import time
import threading
import asyncio
import logging
import traceback
from queue import Empty
import pykka

from api import ArtifactsClient
from broker import MessageType, PubSub, BotUpdateMessage
from models import Character
from tasks import TaskContext
from world import World
from errors import CODE_CHARACTER_INVENTORY_FULL


class Bot(pykka.ThreadingActor):
    """I'm Botman"""

    def __init__(
        self,
        name: str,
        token: str,
        pubsub: PubSub,
        world: World,
    ):
        super().__init__()
        self.name = name
        self.token = token
        self.pubsub = pubsub
        self.world = world
        self.character = None  # Will be fetched in execution loop
        self.api = None  # Will be created in execution loop
        self.current_task = None
        self.task_queue = []

        # Subscribe to bot-specific messages
        self.message_queue = pubsub.subscribe(f"bot.{name}.message")

        # Execution loop
        self.running = False
        self.execution_thread = None
        self.loop = None

        # File logger for detailed error tracking
        self.logger = logging.getLogger(f"botman.bot.{name}")

    def on_start(self):
        self.running = True
        self.execution_thread = threading.Thread(target=self._execution_loop)
        self.execution_thread.daemon = True
        self.execution_thread.start()
        self._log("Started")
        self._publish_status()

    def on_stop(self):
        self.running = False
        if self.execution_thread:
            self.execution_thread.join(timeout=2)

    def _execution_loop(self):
        # Create async event loop for this thread
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        # Initialize API client and fetch character data in this thread's event loop
        try:
            self.api = ArtifactsClient(self.token)
            self.character = self.loop.run_until_complete(
                self.api.get_character(self.name)
            )
            self._log(f"Initialized (Lvl {self.character.level})")
            self._publish_status()
        except Exception as e:
            error_msg = f"Failed to initialize: {e}"
            self._log(error_msg, level="ERROR")
            self.logger.error(f"Initialization error:\n{traceback.format_exc()}")
            self.running = False
            return

        while self.running:
            try:
                # Check for messages
                try:
                    message = self.message_queue.get_nowait()
                    self._handle_message(message)
                except Empty:
                    pass

                # Can only act if not on cooldown
                if not self.character.can_act():
                    self._publish_status()
                    time.sleep(0.5)
                    continue

                # Start next task if idle and ready
                if not self.current_task and self.task_queue:
                    self.current_task = self.task_queue.pop(0)
                    self._log(f"Starting task: {self.current_task.description()}")
                    self._publish_status()

                # Execute current task
                if self.current_task:
                    try:
                        # Create context for task execution
                        context = TaskContext(
                            character=self.character, api=self.api, world=self.world
                        )

                        # Execute task asynchronously
                        result = self.loop.run_until_complete(
                            self.current_task.execute(context)
                        )

                        # Process any log messages from the task
                        if result.log_messages:
                            for message, level in result.log_messages:
                                self._log(message, level=level)

                        # Update character state
                        if result.character:
                            self.character = result.character

                        # Handle task result
                        if result.completed:
                            self._log(
                                f"Task completed: {self.current_task.description()}"
                            )
                            self.current_task = None

                        elif result.paused:
                            # Autonomous recovery based on error code
                            self._handle_paused_task(self.current_task, result)
                            self.current_task = None

                        elif result.error:
                            # Task failed permanently
                            self._log(f"Task failed: {result.error}", level="ERROR")
                            self.current_task = None

                        self._publish_status()

                    except Exception as e:
                        error_msg = f"Task execution exception: {e}"
                        self._log(error_msg, level="ERROR")

                        # Log full traceback to file
                        self.logger.error(
                            f"Task execution exception for task '{self.current_task.description()}':\n"
                            f"{traceback.format_exc()}"
                        )

                        self.current_task = None
                        self._publish_status()

                time.sleep(0.01)

            except Exception as e:
                error_msg = f"Execution loop error: {e}"
                self._log(error_msg, level="ERROR")

                # Log full traceback to file
                self.logger.error(f"Execution loop error:\n{traceback.format_exc()}")

                time.sleep(1)

        # Cleanup: Close API client connections before closing the event loop
        try:
            if self.api is not None:
                self.loop.run_until_complete(self.api.close())
        except Exception as e:
            self.logger.error(f"Error closing API client: {e}")

        # Cleanup loop
        self.loop.close()

    def _handle_paused_task(self, task, result):
        """Handle paused task with autonomous recovery"""
        error_code = self._extract_error_code(result.error)

        if error_code == CODE_CHARACTER_INVENTORY_FULL:
            # TODO: Import and use DepositAllTask when implemented
            self._log(
                "Inventory full - need to implement DepositAllTask for recovery",
                level="WARNING",
            )
            # For now, just re-queue the task (will fail again)
            # self.task_queue.insert(0, task)
            # self.task_queue.insert(0, DepositAllTask())

        else:
            self._log(
                f"Task paused with unknown error code {error_code}, cannot auto-recover",
                level="WARNING",
            )

    def _extract_error_code(self, error_str):
        """Extract error code from error string like '[497] Message'"""
        if not error_str:
            return None
        try:
            # Extract number between brackets
            start = error_str.find("[")
            end = error_str.find("]")
            if start != -1 and end != -1:
                return int(error_str[start + 1 : end])
        except (ValueError, IndexError):
            pass
        return None

    def _handle_message(self, message):
        """Handle incoming messages"""
        data = message.data
        self._log(f"Received message type: {data.get('type')}")

        if data.get("type") == MessageType.TASK_CREATE:
            task = data.get("task")
            if task:
                self.task_queue.append(task)
                self._log(f"Task queued: {task.description()}")
                self._publish_status()

        elif data.get("type") == MessageType.STATUS_REQUEST:
            self._publish_status()

    def _get_status(self) -> str:
        """Calculate current status based on character state"""
        if self.current_task:
            return "Busy"
        elif not self.character.can_act():
            return "Cooldown"
        elif self.task_queue:
            return "Ready"
        else:
            return "Idle"

    def _publish_status(self):
        """Publish status to UI"""
        status_msg = BotUpdateMessage(
            bot_name=self.name,
            status=self._get_status(),
            current_task=self.current_task.description() if self.current_task else None,
            progress=self.current_task.progress() if self.current_task else "0/0",
            cooldown=int(self.character.ready_in()),
            character=self.character,
        )

        self.pubsub.publish(
            "ui.bot_update",
            {"type": "bot_update", "data": status_msg},
            sender=self.name,
        )

    def _log(self, message: str, level: str = "INFO"):
        """Publish log message"""
        self.pubsub.publish(
            "ui.log",
            {
                "type": MessageType.LOG,
                "level": level,
                "source": self.name,
                "message": message,
                "timestamp": time.time(),
            },
            sender=self.name,
        )
