import asyncio
import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fasthtml.common import *
from monsterui.all import *

from botman.web.bridge import UIBridge
from botman.core.bot import BotActor
from botman.core.api import ArtifactsClient
from botman.core.world import World
from botman.web.components import DashboardPage, BotCard, CharacterDetailPage
from botman.core.tasks.gather import GatherTask


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
    return logging.getLogger("botman")


@asynccontextmanager
async def lifespan(app):
    load_dotenv()
    logger = setup_logging()

    token = os.getenv("ARTIFACTS_TOKEN")
    if not token:
        logger.error("ARTIFACTS_TOKEN not found in .env file")
        raise ValueError("ARTIFACTS_TOKEN not found in .env file")

    character_names = os.getenv("CHARACTER_NAMES", "AAA,BBB,CCC,DDD,EEE").split(",")
    logger.info(f"Starting Bot Manager with {len(character_names)} characters")

    ui_bridge = UIBridge()
    await ui_bridge.start()

    async with ArtifactsClient(token) as api:
        world = await World.create(api)
    logger.info(
        f"Loaded world: {len(world.items)} items, {len(world.resources)} resources, "
        f"{len(world.maps)} maps, {len(world.monsters)} monsters"
    )

    bots = {}
    for name in character_names:
        try:
            bot = BotActor(name, token, ui_bridge, world)
            await bot.start()
            bots[name] = bot
            logger.info(f"Started bot: {name}")
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
    hdrs=(
        *Theme.rose.headers(mode='dark'),
        Script(src="https://unpkg.com/htmx-ext-sse@2.2.3/sse.js"),
    ),
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
    return Html(
        Head(
            Title("Botman"),
            *Theme.rose.headers(mode='dark'),
            Script(src="https://unpkg.com/htmx-ext-sse@2.2.3/sse.js"),
        ),
        Body(
            page_content,
            hx_ext="sse",
            sse_connect="/events",
            id="app-body",
            cls="bg-gray-600"
        )
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
                        # Debug logging
                        app.state.logger.info(
                            f"[{bot_name}] Layer: {character.layer}, Position: ({character.position.x}, {character.position.y}) | "
                            f"Map: {map_tile.name if map_tile else 'None'} | "
                            f"Skin: {map_tile.skin if map_tile else 'None'} | "
                            f"Content: {map_tile.content if map_tile else 'None'}"
                        )
                    yield sse_message(BotCard(bot_name, bot_state, map_tile), event=f"bot_changed_{bot_name}")

                elif event_type == 'log':
                    from botman.web.components import LogEntry
                    yield sse_message(LogEntry(data), event="log")

        finally:
            # Always cleanup on disconnect
            await app.state.ui_bridge.ask({
                'type': 'unsubscribe',
                'queue': subscriber_queue
            })
            app.state.logger.info(f"SSE: Client disconnected. Active: {len(app.state.ui_bridge.subscribers)}")

    return EventStream(event_generator())


@rt
async def bot_task(app, bot_name: str, task_type: str, task_params: str):
    if bot_name not in app.state.bots:
        return ""

    bot = app.state.bots[bot_name]

    try:
        if task_type == "gather":
            parts = task_params.split()
            if len(parts) < 2:
                return ""

            resource_code, target_amount = parts[0], int(parts[1])
            task = GatherTask(resource_code=resource_code, target_amount=target_amount)
            await bot.tell({'type': 'task_create', 'task': task})
            return ""
        else:
            return ""
    except Exception as e:
        app.state.logger.error(f"Error adding task: {e}")
        return ""


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
    return Html(
        Head(
            Title(f"{bot_name} - Bot Manager"),
            *Theme.rose.headers(mode='dark'),
            Script(src="https://unpkg.com/htmx-ext-sse@2.2.3/sse.js"),
        ),
        Body(
            page_content,
            hx_ext="sse",
            sse_connect="/events",
            id="app-body",
            cls="bg-gray-600"
        )
    )
