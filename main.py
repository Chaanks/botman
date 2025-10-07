import asyncio
import time
from textual.app import App
from textual.containers import Vertical
from textual.widgets import Header, Footer, Static, Log, Input
from textual.binding import Binding
from queue import Empty
import threading

from broker import PubSub, MessageType
from bot import Bot
from tasks import HelloTask
from api import ArtifactsClient


class BotStatusWidget(Static):
    """Display single bot status"""

    def __init__(self, bot_name: str):
        super().__init__()
        self.bot_name = bot_name
        self.bot_status = "Unknown"
        self.current_task = "None"
        self.task_progress = "0/0"
        self.task_cooldown = 0

    def update_status(self, status: str, task: str, progress: str, cooldown: int):
        self.bot_status = status
        self.current_task = task or "None"
        self.task_progress = progress
        self.task_cooldown = cooldown
        self.refresh()

    def render(self) -> str:
        status_color = {
            "Idle": "green",
            "Ready": "cyan",
            "Busy": "yellow",
            "Cooldown": "red",
        }.get(self.bot_status, "white")

        return f"""[bold]{self.bot_name}[/bold]
                Status: [{status_color}]{self.bot_status}[/{status_color}]
                Task: {self.current_task}
                Progress: {self.task_progress}
                Cooldown: {self.task_cooldown}s
                """


class BotManagerUI(App):
    """Minimal Textual UI for bot management"""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 2;
        grid-gutter: 1;
    }
    
    #bots {
        column-span: 1;
        row-span: 1;
    }
    
    #logs {
        column-span: 1;
        row-span: 2;
    }
    
    #input {
        column-span: 1;
        row-span: 1;
    }
    
    BotStatusWidget {
        border: solid $accent;
        padding: 1;
        margin: 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("h", "hello", "Test Hello Task"),
    ]

    def __init__(self, pubsub: PubSub, bots: list):
        super().__init__()
        self.pubsub = pubsub
        self.bots = bots
        self.bot_widgets = {}

        # Subscribe to UI updates
        self.ui_queue = pubsub.subscribe("ui.bot_update")
        self.log_queue = pubsub.subscribe("ui.log")

        # Background thread to process messages
        self.running = True
        self.message_thread = None

    def compose(self):
        yield Header()

        # Bot status area
        with Vertical(id="bots"):
            for bot_name in self.bots:
                widget = BotStatusWidget(bot_name)
                self.bot_widgets[bot_name] = widget
                yield widget

        # Log area
        with Vertical(id="logs"):
            yield Static("[bold]Logs[/bold]")
            yield Log(id="log_viewer")

        # Command input
        with Vertical(id="input"):
            yield Static("[bold]Command[/bold]")
            yield Input(placeholder="Enter command...", id="command_input")

        yield Footer()

    def on_mount(self):
        """Start message processing thread"""
        self.message_thread = threading.Thread(target=self._process_pubsub_messages)
        self.message_thread.daemon = True
        self.message_thread.start()

    def _process_pubsub_messages(self):
        """Process messages from pubsub in background thread"""
        while self.running:
            try:
                # Process bot updates
                try:
                    message = self.ui_queue.get_nowait()
                    data = message.data.get("data")
                    if data:
                        # Schedule UI update on main thread
                        self.call_from_thread(
                            self._update_bot_status,
                            data.bot_name,
                            data.status,
                            data.current_task,
                            data.progress,
                            data.cooldown,
                        )
                except Empty:
                    pass

                # Process logs
                try:
                    message = self.log_queue.get_nowait()
                    data = message.data
                    log_msg = f"[{data['level']}] {data['source']}: {data['message']}"
                    self.call_from_thread(self._add_log, log_msg)
                except Empty:
                    pass

            except Exception as e:
                print(f"Error processing messages: {e}")

            time.sleep(0.01)

    def _update_bot_status(
        self, bot_name: str, status: str, task: str, progress: str, cooldown: int
    ):
        """Update bot widget (called from main thread)"""
        if bot_name in self.bot_widgets:
            self.bot_widgets[bot_name].update_status(status, task, progress, cooldown)

    def _add_log(self, message: str):
        """Add log entry (called from main thread)"""
        log_viewer = self.query_one("#log_viewer", Log)
        log_viewer.write_line(message)

    def action_hello(self):
        """Send hello task to first bot"""
        if self.bots:
            task = HelloTask(message="Hello from UI!", target_count=5)
            self.pubsub.publish(
                f"bot.{self.bots[0]}.message",
                {"type": MessageType.TASK_CREATE, "task": task},
            )
            self._add_log(f"Sent hello task to {self.bots[0]}")

    def on_input_submitted(self, event: Input.Submitted):
        """Handle command input"""
        command = event.value.strip()
        event.input.value = ""

        if command.startswith("hello"):
            parts = command.split()
            count = int(parts[1]) if len(parts) > 1 else 3
            target_bot = parts[2] if len(parts) > 2 else self.bots[0]

            task = HelloTask(message=f"Hello #{count}", target_count=count)
            self.pubsub.publish(
                f"bot.{target_bot}.message",
                {"type": MessageType.TASK_CREATE, "task": task},
            )
            self._add_log(f"Sent hello task to {target_bot}")
        else:
            self._add_log(f"Unknown command: {command}")

    def on_unmount(self):
        """Cleanup on exit"""
        self.running = False


async def initialize_bots(token: str, character_names: list):
    """Initialize bots with real characters from API"""
    api = ArtifactsClient(token)
    pubsub = PubSub()
    bot_actors = []

    print("Initializing bots...")

    for name in character_names:
        try:
            character = await api.get_character(name)
            print(f"✓ Loaded character: {character.name} (Lvl {character.level})")

            bot = Bot.start(name, pubsub, character, api)
            bot_actors.append(bot)

        except Exception as e:
            print(f"✗ Failed to load {name}: {e}")

    return pubsub, bot_actors, [name for name in character_names]


def main():
    import os

    TOKEN = os.getenv("ARTIFACTS_TOKEN")
    if not TOKEN:
        print("Error: ARTIFACTS_TOKEN environment variable not set")
        return

    CHARACTER_NAMES = ["AAA"]

    pubsub, bot_actors, bot_names = asyncio.run(initialize_bots(TOKEN, CHARACTER_NAMES))

    if not bot_actors:
        print("Error: No bots initialized")
        return

    print(f"\nStarted {len(bot_actors)} bots")
    print("Starting UI...")

    app = BotManagerUI(pubsub, bot_names)

    try:
        app.run()
    finally:
        print("\nStopping bots...")
        for bot in bot_actors:
            bot.stop()
        print("Shutdown complete")


if __name__ == "__main__":
    main()
