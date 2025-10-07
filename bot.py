import time
import threading
from queue import Empty
import pykka

from api import ArtifactsClient
from broker import MessageType, PubSub, BotUpdateMessage
from models import Character
from tasks import TaskContext


class Bot(pykka.ThreadingActor):
    """I'm Botman."""

    def __init__(
        self, name: str, pubsub: PubSub, character: Character, api: ArtifactsClient
    ):
        super().__init__()
        self.name = name
        self.pubsub = pubsub
        self.character = character
        self.api = api
        self.current_task = None
        self.task_queue = []

        # Subscribe to bot-specific messages
        self.message_queue = pubsub.subscribe(f"bot.{name}.message")

        # Execution loop
        self.running = False
        self.execution_thread = None

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
                        context = TaskContext(character=self.character, api=self.api)

                        result = self.current_task.execute(context)

                        # Handle errors
                        if result.error:
                            self._log(f"Task error: {result.error}", level="ERROR")
                            self.current_task = None
                            self._publish_status()
                            continue

                        # Process any log messages from the task
                        if result.log_messages:
                            for message, level in result.log_messages:
                                self._log(message, level=level)

                        # Update character state
                        if result.character:
                            self.character = result.character

                        # Check completion
                        if result.completed:
                            self._log(
                                f"Task completed: {self.current_task.description()}"
                            )
                            self.current_task = None

                        self._publish_status()

                    except Exception as e:
                        self._log(f"Task execution exception: {e}", level="ERROR")
                        self.current_task = None
                        self._publish_status()

                time.sleep(0.01)

            except Exception as e:
                self._log(f"Execution loop error: {e}", level="ERROR")
                time.sleep(1)

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
