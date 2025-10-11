import asyncio
import os
import logging
import tomllib
from pathlib import Path
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fasthtml.common import *
from monsterui.all import *

from botman.web.bridge import UIBridge
from botman.core.bot import Bot, BotRole
from botman.core.api import ArtifactsClient
from botman.core.world import World
from botman.core.models import Skill
from botman.web.components import DashboardPage, BotCard, CharacterDetailPage, TaskFormFields
from botman.core.tasks.registry import TaskFactory


def setup_logging(log_file="logs/botman.log"):
    log_dir = os.path.dirname(log_file)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="a"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    return logging.getLogger("botman")


@asynccontextmanager
async def lifespan(app):
    load_dotenv()
    logger = setup_logging()

    # Load API token from .env
    token = os.getenv("ARTIFACTS_TOKEN")
    if not token:
        logger.error("ARTIFACTS_TOKEN not found in .env file")
        raise ValueError("ARTIFACTS_TOKEN not found in .env file")

    # Load bot configuration from config.toml
    config_path = Path(__file__).parent.parent.parent / "config.toml"
    if not config_path.exists():
        logger.error(f"config.toml not found at {config_path}")
        raise ValueError(f"config.toml not found at {config_path}")

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    bot_configs = config.get("bots", [])
    if not bot_configs:
        logger.error("No bots configured in config.toml")
        raise ValueError("No bots configured in config.toml")

    logger.info(f"Starting Bot Manager with {len(bot_configs)} characters")

    ui_bridge = UIBridge()
    await ui_bridge.start()

    async with ArtifactsClient(token) as api:
        world = await World.create(api)
    logger.info(
        f"Loaded world: {len(world.items)} items, {len(world.resources)} resources, "
        f"{len(world.maps)} maps, {len(world.monsters)} monsters"
    )

    bots = {}
    for bot_config in bot_configs:
        name = bot_config["name"]
        role = BotRole(bot_config["role"])
        skills = [Skill(skill) for skill in bot_config.get("skills", [])]

        try:
            bot = Bot(name, token, ui_bridge, world, role, skills)
            await bot.start()
            bots[name] = bot
            skills_str = ", ".join([s.value for s in skills]) if skills else "none"
            logger.info(f"Started bot: {name} (role: {role.value}, skills: {skills_str})")
        except Exception as e:
            logger.error(f"Failed to start bot {name}: {e}")

    app.state.ui_bridge = ui_bridge
    app.state.bots = bots
    app.state.world = world
    app.state.logger = logger

    logger.info("Bot Manager is running on http://localhost:5173")
    yield

    for bot in bots.values():
        await bot.stop()
    if ui_bridge:
        await ui_bridge.stop()
    logger.info("Bot Manager shutdown complete")


app, rt = fast_app(
    hdrs=(*Theme.rose.headers(mode='dark'), Script(src="https://unpkg.com/htmx-ext-sse@2.2.3/sse.js")),
    lifespan=lifespan
)


@rt
async def index(app, req):
    state = await app.state.ui_bridge.ask({'type': 'get_state'})
    page_content = DashboardPage(state, app.state.world)

    # If htmx request, return just content
    if req.headers.get('HX-Request'):
        return page_content

    # Full page load: wrap with SSE connection
    return Title("Botman"), Body(
        page_content,
        hx_ext="sse",
        sse_connect="/events",
        id="app-body",
        cls="bg-gray-600"
    )


@rt
async def events(app):
    async def event_generator():
        subscriber_queue = asyncio.Queue()

        # Subscribe to updates
        await app.state.ui_bridge.ask({
            'type': 'subscribe',
            'queue': subscriber_queue
        })
        app.state.logger.info(f"SSE: Client connected. Active: {len(app.state.ui_bridge.subscribers)}")

        try:
            # Send initial connection message
            yield f"data: Connected\n\n"

            # Stream updates
            while True:
                event_type, data = await subscriber_queue.get()

                if event_type == 'bot_changed':
                    bot_name = data['bot_name']
                    bot_state = data['data']
                    map_tile = None
                    if bot_state.get('character'):
                        character = bot_state['character']
                        map_tile = app.state.world.map_for_character(character)
                    app.state.logger.debug(f"SSE: Sending bot_changed_{bot_name} event")
                    yield sse_message(BotCard(bot_name, bot_state, map_tile), event=f"bot_changed_{bot_name}")

                elif event_type == 'log':
                    from botman.web.components import LogEntry
                    app.state.logger.debug(f"SSE: Sending log event from {data.get('source', 'unknown')}")
                    yield sse_message(LogEntry(data), event="log")

        finally:
            # Always cleanup on disconnect
            await app.state.ui_bridge.ask({
                'type': 'unsubscribe',
                'queue': subscriber_queue
            })
            app.state.logger.info(f"SSE: Client disconnected. Active: {len(app.state.ui_bridge.subscribers)}")

    return EventStream(event_generator())


@rt("/bot_task")
async def post(app, req):
    """Handle task creation from web UI"""
    # Get form data
    form_data = await req.form()
    form_dict = dict(form_data)

    bot_name = form_dict.get("bot_name")
    task_type = form_dict.get("task_type")

    app.state.logger.info(f"bot_task called: bot={bot_name}, type={task_type}, params={form_dict}")

    if not bot_name or bot_name not in app.state.bots:
        app.state.logger.error(f"Bot {bot_name} not found")
        return ""

    bot = app.state.bots[bot_name]

    try:
        # Extract task parameters (exclude bot_name and task_type)
        task_params = {k: v for k, v in form_dict.items() if k not in ("bot_name", "task_type")}

        # Special handling for deposit mode
        if task_type == "deposit":
            deposit_mode = task_params.pop("deposit_mode", "single")
            if deposit_mode == "all":
                task_params = {"deposit_all": True}
            # else keep item_code and quantity

        # Special handling for recycle checkbox
        if task_type == "craft" and "recycle" in task_params:
            task_params["recycle"] = task_params["recycle"] == "true"

        # Create task using factory
        task = TaskFactory.create_task(task_type, task_params)

        if not task:
            app.state.logger.error(f"Unknown task type: {task_type}")
            return ""

        app.state.logger.info(f"Creating {task_type} task for {bot_name}: {task.description()}")
        await bot.tell({'type': 'task_create', 'task': task})
        app.state.logger.info(f"Task queued successfully for {bot_name}")
        return ""

    except ValueError as e:
        app.state.logger.error(f"Invalid task parameters: {e}")
        return ""
    except Exception as e:
        app.state.logger.error(f"Error adding task: {e}", exc_info=True)
        return ""


@rt("/task_form_fields")
async def task_form_fields(app, task_type: str, bot_name: str):
    """Return dynamic form fields based on task type"""
    return TaskFormFields(task_type, bot_name)


@rt("/deposit_mode_fields")
async def deposit_mode_fields(app, deposit_mode: str, bot_name: str):
    """Return dynamic fields for deposit mode"""
    if deposit_mode == "all":
        return Div(
            P("All items in inventory will be deposited", cls="text-sm text-gray-400 italic"),
            cls="mt-4"
        )
    else:
        return Div(
            Div(
                Label("Item Code", cls="text-sm text-gray-400 mb-1 block"),
                Input(
                    type="text",
                    name="item_code",
                    placeholder="e.g., copper_ore, ash_wood",
                    required=True,
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                ),
            ),
            Div(
                Label("Quantity", cls="text-sm text-gray-400 mb-1 block"),
                Input(
                    type="number",
                    name="quantity",
                    placeholder="10",
                    value="10",
                    min="1",
                    required=True,
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                ),
            ),
            cls="space-y-4"
        )


@rt
async def bot_restart(app, bot_name: str):
    if bot_name not in app.state.bots:
        return ""

    bot = app.state.bots[bot_name]
    await bot.stop()
    await bot.start()
    return ""


@rt
async def bot_clear_queue(app, bot_name: str):
    if bot_name not in app.state.bots:
        return ""

    bot = app.state.bots[bot_name]
    bot.task_queue.clear()
    return ""


@rt("/character/{bot_name}")
async def character(app, req, bot_name: str):
    state = await app.state.ui_bridge.ask({'type': 'get_state'})
    bot_state = state['bots'].get(bot_name)

    if not bot_state:
        return Div("Character not found", A("Back to Dashboard", href="/"))

    page_content = CharacterDetailPage(bot_name, bot_state)

    # If htmx request, return just content
    if req.headers.get('HX-Request'):
        return page_content

    # Full page load: wrap with SSE connection
    return Title(f"{bot_name} - Bot Manager"), Body(
        page_content,
        hx_ext="sse",
        sse_connect="/events",
        id="app-body",
        cls="bg-gray-600"
    )
