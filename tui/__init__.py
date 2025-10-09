"""Textual TUI for bot management"""

import time
import httpx
from pathlib import Path
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.containers import Vertical, Horizontal, Container, ScrollableContainer
from textual.widgets import Header, Footer, Static, DataTable, Log, Input, Label
from textual.binding import Binding
from textual.reactive import reactive
from queue import Empty
import threading
from io import BytesIO

try:
    from textual_image.widget import Image

    IMAGES_SUPPORTED = True
except ImportError:
    IMAGES_SUPPORTED = False
    Image = None

from broker import PubSub, MessageType
from tasks.gather import GatherTask

# Image cache directory
CACHE_DIR = Path.home() / ".cache" / "botman" / "items"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ===== Helper Functions =====


def get_item_image_cached(item_code: str) -> Path | None:
    """Get cached small item image if available"""
    cache_path = CACHE_DIR / f"{item_code}_small.png"
    return cache_path if cache_path.exists() else None


def download_item_image(item_code: str) -> Path | None:
    """Download and resize item image in background"""
    original_cache_path = CACHE_DIR / f"{item_code}.png"
    small_cache_path = CACHE_DIR / f"{item_code}_small.png"

    # Return if small version already exists
    if small_cache_path.exists():
        return small_cache_path

    url = f"https://artifactsmmo.com/images/items/{item_code}.png"

    try:
        # Step 1: Download original image if not cached
        if not original_cache_path.exists():
            print(f"Downloading {item_code} from {url}...")
            response = httpx.get(url, timeout=10.0, follow_redirects=True)
            response.raise_for_status()

            # Save original
            with open(original_cache_path, "wb") as f:
                f.write(response.content)
            print(f"✓ Downloaded {item_code}")

        # Step 2: Resize to small icon
        from PIL import Image as PILImage

        print(f"Resizing {item_code}...")
        pil_img = PILImage.open(original_cache_path)
        pil_img = pil_img.resize((16, 16), PILImage.Resampling.LANCZOS)
        pil_img.save(small_cache_path, "PNG")
        print(f"✓ Resized {item_code} to 16x16")

        return small_cache_path

    except httpx.HTTPError as e:
        print(f"HTTP error downloading {item_code}: {e}")
        return None
    except ImportError as e:
        print(f"PIL not available: {e}")
        # Return original if PIL not available
        if original_cache_path.exists():
            return original_cache_path
        return None
    except Exception as e:
        print(f"Failed to process {item_code}: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        return None


# ===== Widgets =====


class InventoryItem(Static):
    """Display single inventory item with image"""

    CSS = """
    InventoryItem {
        height: auto;
        layout: horizontal;
        padding: 0 1;
        margin-bottom: 1;
        background: $surface;
    }

    InventoryItem .item-icon {
        width: 2;
        height: 1;
        margin-right: 1;
    }

    InventoryItem .item-info {
        width: 1fr;
        height: auto;
        content-align: left middle;
    }
    """

    def __init__(self, item_code: str, quantity: int, slot: int, bot_screen=None):
        super().__init__()
        self.item_code = item_code
        self.quantity = quantity
        self.slot = slot
        self.image_loaded = False
        self.bot_screen = bot_screen

    def compose(self) -> ComposeResult:
        # Check if image is already cached
        if IMAGES_SUPPORTED:
            cached_path = get_item_image_cached(self.item_code)
            if cached_path:
                # Use pre-resized small icon
                try:
                    img = Image(str(cached_path))
                    img.add_class("item-icon")
                    yield img
                except Exception as e:
                    # Fallback if image fails
                    yield Static(f"[red]✗[/red]", classes="item-icon")
            else:
                # Show placeholder
                yield Static("[dim]⏳[/dim]", classes="item-icon")
                # Start download in background
                threading.Thread(target=self._download_image, daemon=True).start()
        else:
            # No image support - show icon
            yield Static("[cyan]▪[/cyan]", classes="item-icon")

        yield Label(
            f"[bold]{self.item_code}[/bold] x{self.quantity}", classes="item-info"
        )

    def _download_image(self):
        """Download image in background thread"""
        try:
            # Log start
            if self.bot_screen:
                self.app.call_from_thread(
                    self.bot_screen.add_log,
                    f"[dim]Downloading image for {self.item_code}...[/dim]",
                )

            image_path = download_item_image(self.item_code)

            if image_path and IMAGES_SUPPORTED:
                # Update UI on main thread
                self.app.call_from_thread(self._set_image, str(image_path))
                if self.bot_screen:
                    self.app.call_from_thread(
                        self.bot_screen.add_log,
                        f"[green]✓ Downloaded {self.item_code}[/green]",
                    )
            else:
                # Download failed - show error icon
                error_msg = f"Download failed for {self.item_code}"
                self.app.call_from_thread(self._set_error, error_msg)
                if self.bot_screen:
                    self.app.call_from_thread(
                        self.bot_screen.add_log, f"[red]{error_msg}[/red]"
                    )
        except Exception as e:
            # Unexpected error
            error_msg = f"Error downloading {self.item_code}: {type(e).__name__}: {e}"
            self.app.call_from_thread(self._set_error, error_msg)
            if self.bot_screen:
                self.app.call_from_thread(
                    self.bot_screen.add_log, f"[red]{error_msg}[/red]"
                )

    def _set_image(self, image_path: str):
        """Set image on main thread"""
        if self.image_loaded:
            return
        self.image_loaded = True

        try:
            # Replace placeholder with actual image (already resized)
            placeholder = self.query_one(".item-icon")
            img = Image(image_path)
            img.add_class("item-icon")
            placeholder.remove()
            # Mount new image as first child
            self.mount(img, before=0)
        except Exception as e:
            # If mounting fails, show error
            try:
                placeholder = self.query_one(".item-icon")
                placeholder.update("[red]✗[/red]")
            except:
                pass

    def _set_error(self, error_msg: str = "Failed"):
        """Set error icon on main thread"""
        if self.image_loaded:
            return
        self.image_loaded = True

        try:
            placeholder = self.query_one(".item-icon")
            placeholder.update("[red]✗[/red]")
            # Try to log to parent screen if possible
            parent = self.parent
            while parent:
                if isinstance(parent, BotScreen):
                    parent.add_log(f"[red]{error_msg}[/red]")
                    break
                parent = parent.parent
        except:
            pass


class BotStatusCard(Static):
    """Display single bot status"""

    bot_name: reactive[str] = reactive("")
    status: reactive[str] = reactive("Unknown")
    current_task: reactive[str | None] = reactive(None)
    progress: reactive[str] = reactive("0/0")
    cooldown: reactive[int] = reactive(0)

    def __init__(self, bot_name: str):
        super().__init__()
        self.bot_name = bot_name

    def render(self) -> str:
        status_color = {
            "Idle": "green",
            "Ready": "cyan",
            "Busy": "yellow",
            "Cooldown": "red",
        }.get(self.status, "white")

        task_display = self.current_task or "None"

        return f"""[bold]{self.bot_name}[/bold]
Status: [{status_color}]{self.status}[/{status_color}]
Task: {task_display}
Progress: {self.progress}
Cooldown: {self.cooldown}s"""


# ===== Screens =====


class DashboardScreen(Screen):
    """Dashboard showing all bots and system logs"""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "select_bot_1", "Bot 1", show=True),
        Binding("2", "select_bot_2", "Bot 2", show=True),
        Binding("3", "select_bot_3", "Bot 3", show=True),
        Binding("4", "select_bot_4", "Bot 4", show=True),
        Binding("5", "select_bot_5", "Bot 5", show=True),
    ]

    CSS = """
    DashboardScreen {
        layout: vertical;
    }

    #bot_cards_container {
        height: 60%;
        border: solid $accent;
        padding: 1;
    }

    #bot_grid {
        layout: grid;
        grid-size: 3;
        grid-gutter: 1 2;
        height: 1fr;
    }

    #log_container {
        height: 40%;
        border: solid $primary;
        padding: 1;
    }

    BotStatusCard {
        border: solid $success;
        background: $surface;
        padding: 1;
        height: 100%;
    }

    Log {
        height: 1fr;
    }
    """

    def __init__(self, pubsub: PubSub, bot_names: list[str]):
        super().__init__()
        self.pubsub = pubsub
        self.bot_names = bot_names
        self.bot_cards = {}

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="bot_cards_container"):
            yield Label("[bold]Bots - Press 1-5 to select[/bold]")
            with Container(id="bot_grid"):
                for i, bot_name in enumerate(self.bot_names, 1):
                    card = BotStatusCard(bot_name)
                    self.bot_cards[bot_name] = card
                    yield card

        with Container(id="log_container"):
            yield Label("[bold]System Logs[/bold]")
            yield Log(id="system_log")

        yield Footer()

    def update_bot_status(
        self, bot_name: str, status: str, task: str | None, progress: str, cooldown: int
    ):
        """Update bot card"""
        if bot_name in self.bot_cards:
            card = self.bot_cards[bot_name]
            card.status = status
            card.current_task = task
            card.progress = progress
            card.cooldown = cooldown

    def add_log(self, message: str):
        """Add log entry"""
        log_viewer = self.query_one("#system_log", Log)
        log_viewer.write_line(message)

    def _select_bot(self, index: int):
        """Select bot by index"""
        if 0 <= index < len(self.bot_names):
            bot_name = self.bot_names[index]
            self.app.push_screen(BotScreen(self.pubsub, bot_name))

    def action_select_bot_1(self):
        self._select_bot(0)

    def action_select_bot_2(self):
        self._select_bot(1)

    def action_select_bot_3(self):
        self._select_bot(2)

    def action_select_bot_4(self):
        self._select_bot(3)

    def action_select_bot_5(self):
        self._select_bot(4)


class BotScreen(Screen):
    """Individual bot detail view with commands"""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("q", "quit", "Quit"),
    ]

    CSS = """
    BotScreen {
        layout: grid;
        grid-size: 2 3;
        grid-gutter: 1;
    }

    #bot_info {
        border: solid $accent;
        padding: 1;
        column-span: 1;
        row-span: 1;
    }

    #command_container {
        border: solid $success;
        padding: 1;
        column-span: 1;
        row-span: 1;
    }

    #inventory_container {
        border: solid $warning;
        padding: 1;
        column-span: 1;
        row-span: 2;
    }

    #inventory_scroll {
        height: 1fr;
    }

    #inventory_items {
        layout: vertical;
        height: auto;
    }

    #bot_log_container {
        border: solid $primary;
        padding: 1;
        column-span: 2;
        row-span: 1;
    }

    DataTable {
        height: 1fr;
    }

    Log {
        height: 1fr;
    }
    """

    def __init__(self, pubsub: PubSub, bot_name: str):
        super().__init__()
        self.pubsub = pubsub
        self.bot_name = bot_name
        self.character = None

    def compose(self) -> ComposeResult:
        yield Header()

        with Container(id="bot_info"):
            yield BotStatusCard(self.bot_name)

        with Container(id="command_container"):
            yield Label(f"[bold]Commands for {self.bot_name}[/bold]")
            yield Label("gather <resource> <amount> - Gather resources")
            yield Input(placeholder="Enter command...", id="command_input")

        with Container(id="inventory_container"):
            yield Label("[bold]Inventory[/bold]")
            with ScrollableContainer(id="inventory_scroll"):
                yield Container(id="inventory_items")

        with Container(id="bot_log_container"):
            yield Label(f"[bold]Logs for {self.bot_name}[/bold]")
            yield Log(id="bot_log")

        yield Footer()

    def on_mount(self) -> None:
        """Initialize inventory display"""
        pass

    def update_bot_status(
        self,
        status: str,
        task: str | None,
        progress: str,
        cooldown: int,
        character=None,
    ):
        """Update bot status card and inventory"""
        card = self.query_one(BotStatusCard)
        card.status = status
        card.current_task = task
        card.progress = progress
        card.cooldown = cooldown

        if character:
            self.character = character
            self._update_inventory()

    def _update_inventory(self):
        """Update inventory display with images"""
        if not self.character:
            return

        container = self.query_one("#inventory_items", Container)

        # Clear existing items
        container.remove_children()

        # Debug: show what's in inventory
        inv_items = [
            f"{item.code}(slot:{item.slot})" for item in self.character.inventory
        ]
        self.add_log(f"[yellow]DEBUG: Inventory={inv_items}[/yellow]")

        # Add inventory items with images
        for item in self.character.inventory:
            inventory_item = InventoryItem(
                item.code, item.quantity, item.slot, bot_screen=self
            )
            container.mount(inventory_item)

    def add_log(self, message: str):
        """Add log entry for this bot"""
        log_viewer = self.query_one("#bot_log", Log)
        log_viewer.write_line(message)

    def action_back(self):
        """Go back to dashboard"""
        self.app.pop_screen()

    def on_input_submitted(self, event: Input.Submitted):
        """Handle command input"""
        command = event.value.strip()
        event.input.value = ""

        if not command:
            return

        if command.startswith("gather"):
            parts = command.split()
            if len(parts) < 3:
                self.add_log("[red]Usage: gather <resource> <amount>[/red]")
                return

            resource = parts[1]
            try:
                amount = int(parts[2])
            except ValueError:
                self.add_log("[red]Amount must be a number[/red]")
                return

            task = GatherTask(resource_code=resource, target_amount=amount)
            self.pubsub.publish(
                f"bot.{self.bot_name}.message",
                {"type": MessageType.TASK_CREATE, "task": task},
            )
            self.add_log(f"[green]Sent gather task: {resource} x{amount}[/green]")

        else:
            self.add_log(f"[red]Unknown command: {command}[/red]")


# ===== Main App =====


class BotManagerUI(App):
    """Bot management TUI application"""

    def __init__(self, pubsub: PubSub, bot_names: list[str]):
        super().__init__()
        self.pubsub = pubsub
        self.bot_names = bot_names

        # Subscribe to UI updates
        self.ui_queue = pubsub.subscribe("ui.bot_update")
        self.log_queue = pubsub.subscribe("ui.log")

        # Background thread to process messages
        self.running = True
        self.message_thread = None

    def on_mount(self) -> None:
        """Start message processing and push dashboard"""
        self.push_screen(DashboardScreen(self.pubsub, self.bot_names))

        self.message_thread = threading.Thread(target=self._process_pubsub)
        self.message_thread.daemon = True
        self.message_thread.start()

    def _process_pubsub(self):
        """Process messages from pubsub in background thread"""
        while self.running:
            try:
                # Process bot updates
                try:
                    message = self.ui_queue.get_nowait()
                    data = message.data.get("data")
                    if data:
                        self.call_from_thread(
                            self._handle_bot_update,
                            data.bot_name,
                            data.status,
                            data.current_task,
                            data.progress,
                            data.cooldown,
                            data.character,
                        )
                except Empty:
                    pass

                # Process logs
                try:
                    message = self.log_queue.get_nowait()
                    data = message.data
                    level_color = {
                        "INFO": "cyan",
                        "WARNING": "yellow",
                        "ERROR": "red",
                        "DEBUG": "dim",
                    }.get(data["level"], "white")
                    log_msg = f"[{level_color}][{data['level']}][/{level_color}] {data['source']}: {data['message']}"
                    self.call_from_thread(self._handle_log, data["source"], log_msg)
                except Empty:
                    pass

            except Exception as e:
                # Silently log errors to avoid crashing
                pass

            time.sleep(0.01)

    def _handle_bot_update(
        self,
        bot_name: str,
        status: str,
        task: str | None,
        progress: str,
        cooldown: int,
        character=None,
    ):
        """Handle bot status update on main thread"""
        # Update dashboard if it's the current screen
        if isinstance(self.screen, DashboardScreen):
            self.screen.update_bot_status(bot_name, status, task, progress, cooldown)

        # Update bot screen if it's showing this bot
        elif isinstance(self.screen, BotScreen) and self.screen.bot_name == bot_name:
            self.screen.update_bot_status(status, task, progress, cooldown, character)

    def _handle_log(self, source: str, log_msg: str):
        """Handle log message on main thread"""
        # Always add to dashboard
        for screen in self.screen_stack:
            if isinstance(screen, DashboardScreen):
                screen.add_log(log_msg)

        # Add to bot screen if showing that bot
        if isinstance(self.screen, BotScreen) and self.screen.bot_name == source:
            self.screen.add_log(log_msg)

    def on_unmount(self):
        """Cleanup on exit"""
        self.running = False
