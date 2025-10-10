"""Main entry point for bot manager - FastHTML + HTMX version"""

import asyncio
import os
import logging
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fasthtml.common import *
from monsterui.all import *

from ui_bridge import UIBridge
from bot import BotActor
from api import ArtifactsClient
from world import World
from components import DashboardPage, BotCard
from tasks.gather import GatherTask


def setup_logging(log_file="botman.log"):
    """Configure logging for the application"""
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
    """Lifespan context manager for startup/shutdown."""
    # Load environment
    load_dotenv()
    logger = setup_logging()

    # Get configuration
    token = os.getenv("ARTIFACTS_TOKEN")
    if not token:
        logger.error("ARTIFACTS_TOKEN not found in .env file")
        raise ValueError("ARTIFACTS_TOKEN not found in .env file")

    character_names = os.getenv("CHARACTER_NAMES", "AAA,BBB,CCC,DDD,EEE").split(",")

    logger.info("Starting Bot Manager with FastHTML + HTMX")
    logger.info(f"Characters: {character_names}")

    # Initialize UIBridge
    ui_bridge = UIBridge()
    await ui_bridge.start()
    logger.info("UIBridge started")

    # Initialize World data
    async with ArtifactsClient(token) as api:
        world = await World.create(api)
    logger.info(
        f"Loaded world: {len(world.items)} items, {len(world.resources)} resources, "
        f"{len(world.maps)} maps, {len(world.monsters)} monsters"
    )

    # Initialize bots
    bots = {}
    for name in character_names:
        try:
            bot = BotActor(name, token, ui_bridge, world)
            await bot.start()
            bots[name] = bot
            logger.info(f"Started bot: {name}")
        except Exception as e:
            logger.error(f"Failed to start bot {name}: {e}")

    logger.info(f"System initialized with {len(bots)} bots")

    # Store in app state
    app.state.ui_bridge = ui_bridge
    app.state.bots = bots
    app.state.world = world
    app.state.logger = logger

    print("✓ Bot Manager is running!")
    print("✓ Open http://localhost:5173 in your browser")

    yield

    # Shutdown
    for bot in bots.values():
        await bot.stop()

    if ui_bridge:
        await ui_bridge.stop()

    print("✓ Bot Manager shutdown complete")


# Create FastHTML app with MonsterUI blue theme (light) and SSE extension
app, rt = fast_app(
    hdrs=(
        *Theme.blue.headers(),
        Script(src="https://unpkg.com/htmx-ext-sse@2.2.2/sse.js"),
    ),
    lifespan=lifespan
)


@rt
async def index(app):
    """Main dashboard page."""
    state = await app.state.ui_bridge.ask({'type': 'get_state'})
    return DashboardPage(state)


@rt
async def events(app):
    """SSE endpoint for real-time updates."""
    async def event_generator():
        """Generate SSE events from UIBridge updates."""
        subscriber_queue = asyncio.Queue()

        # Subscribe to ui_bridge
        result = await app.state.ui_bridge.ask({
            'type': 'subscribe',
            'queue': subscriber_queue
        })

        app.state.logger.info(f"SSE: New client connected. Subscribers: {result.get('subscriber_count', 0)}")

        # Send initial connection message
        yield f"data: Connected to event stream\n\n"

        try:
            while True:
                update = await subscriber_queue.get()
                event_type, data = update

                if event_type == 'bot_changed':
                    bot_name = data['bot_name']
                    bot_state = data['data']
                    app.state.logger.info(f"SSE: Sending bot_changed event for {bot_name}")
                    yield sse_message(BotCard(bot_name, bot_state), event=f"bot_changed_{bot_name}")

                elif event_type == 'log':
                    from components import LogEntry
                    app.state.logger.debug(f"SSE: Sending log event from {data.get('source')}")
                    yield sse_message(LogEntry(data), event="log")

        except asyncio.CancelledError:
            app.state.logger.info("SSE: Client disconnected")
        except Exception as e:
            app.state.logger.error(f"SSE: Error in stream: {e}")
            import traceback
            app.state.logger.error(traceback.format_exc())

    return EventStream(event_generator())


@rt
async def bot_task(app, bot_name: str, task_type: str, task_params: str):
    """Add task to bot queue."""
    if bot_name not in app.state.bots:
        return Div("Bot not found", cls="error")

    bot = app.state.bots[bot_name]

    try:
        if task_type == "gather":
            parts = task_params.split()
            if len(parts) < 2:
                return Div("Invalid params. Format: resource amount", cls="error")

            resource_code, target_amount = parts[0], int(parts[1])
            task = GatherTask(resource_code=resource_code, target_amount=target_amount)

            await bot.tell({'type': 'task_create', 'task': task})

            state = await app.state.ui_bridge.ask({'type': 'get_state'})
            return BotCard(bot_name, state['bots'].get(bot_name, {}))
        else:
            return Div(f"Task type '{task_type}' not implemented yet", cls="error")

    except Exception as e:
        return Div(f"Error: {str(e)}", cls="error")


@rt
async def bot_restart(app, bot_name: str):
    """Restart a bot."""
    if bot_name not in app.state.bots:
        return Div("Bot not found", cls="error")

    bot = app.state.bots[bot_name]
    await bot.stop()
    await bot.start()

    state = await app.state.ui_bridge.ask({'type': 'get_state'})
    return BotCard(bot_name, state['bots'].get(bot_name, {}))


@rt
async def bot_clear_queue(app, bot_name: str):
    """Clear bot task queue."""
    if bot_name not in app.state.bots:
        return Div("Bot not found", cls="error")

    bot = app.state.bots[bot_name]
    bot.task_queue.clear()

    state = await app.state.ui_bridge.ask({'type': 'get_state'})
    return BotCard(bot_name, state['bots'].get(bot_name, {}))


serve(host="100.115.85.125", port=5173)
