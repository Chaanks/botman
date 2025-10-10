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
from botman.web.components import DashboardPage, BotCard
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
        *Theme.blue.headers(),
        Script(src="https://unpkg.com/htmx-ext-sse@2.2.2/sse.js"),
    ),
    lifespan=lifespan
)


@rt
async def index(app):
    state = await app.state.ui_bridge.ask({'type': 'get_state'})
    return DashboardPage(state)


@rt
async def events(app):
    async def event_generator():
        subscriber_queue = asyncio.Queue()
        result = await app.state.ui_bridge.ask({
            'type': 'subscribe',
            'queue': subscriber_queue
        })

        app.state.logger.info(f"SSE: New client connected. Subscribers: {result.get('subscriber_count', 0)}")
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
                    from botman.web.components import LogEntry
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
    if bot_name not in app.state.bots:
        return Div("Bot not found", cls="error")

    bot = app.state.bots[bot_name]
    await bot.stop()
    await bot.start()

    state = await app.state.ui_bridge.ask({'type': 'get_state'})
    return BotCard(bot_name, state['bots'].get(bot_name, {}))


@rt
async def bot_clear_queue(app, bot_name: str):
    if bot_name not in app.state.bots:
        return Div("Bot not found", cls="error")

    bot = app.state.bots[bot_name]
    bot.task_queue.clear()

    state = await app.state.ui_bridge.ask({'type': 'get_state'})
    return BotCard(bot_name, state['bots'].get(bot_name, {}))
