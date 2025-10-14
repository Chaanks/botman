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
from botman.core.bot import Bot
from botman.core.api import ArtifactsClient
from botman.core.world import World
from botman.core.bank import Bank
from botman.core.api.models import Skill, CharacterRole
from botman.core.mrp.orchestrator import JobOrchestrator
from botman.web.components import (
    DashboardPage,
    BotCard,
    CharacterDetailPage,
    TaskFormFields,
    AchievementsPage,
)
from botman.core.tasks.registry import TaskFactory
from botman.core.bot.messages import TaskCreateMessage, SetAutonomousModeMessage
from botman.web.bridge.messages import (
    GetStateMessage,
    SubscribeMessage,
    UnsubscribeMessage,
)
from botman.core.mrp.messages import (
    ListCraftableItemsRequest,
    GetPlanStatusRequest,
    CreatePlanRequest,
)


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
    logging.getLogger("httpx").setLevel(logging.INFO)

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

    # Get account name from config
    account_name = config.get("account_name")
    if not account_name:
        logger.error("account_name not found in config.toml")
        raise ValueError("account_name not found in config.toml")

    bot_configs = config.get("bots", [])
    if not bot_configs:
        logger.error("No bots configured in config.toml")
        raise ValueError("No bots configured in config.toml")

    logger.info(f"Starting Bot Manager with {len(bot_configs)} characters")
    logger.info(f"Account: {account_name}")

    ui_bridge = UIBridge(name="ui", inbox_size=200)
    await ui_bridge.start()

    async with ArtifactsClient(token) as api:
        world = await World.create(api)
    logger.info(
        f"Loaded world: {len(world.items)} items, {len(world.resources)} resources, "
        f"{len(world.maps)} maps, {len(world.monsters)} monsters"
    )

    # Initialize Bank
    bank_actor = Bank(token, name="bank", inbox_size=100)
    await bank_actor.start()
    logger.info("Bank initialized")

    # Initialize JobOrchestrator for MRP system
    orchestrator = JobOrchestrator(world, name="orchestrator", inbox_size=50)
    await orchestrator.start()
    logger.info("JobOrchestrator initialized")

    bots = {}
    for bot_config in bot_configs:
        name = bot_config["name"]
        role = CharacterRole(bot_config["role"])
        skills = [Skill(skill) for skill in bot_config.get("skills", [])]

        try:
            bot = Bot(
                name,
                token,
                ui_bridge,
                world,
                role,
                skills,
                bank_actor,
                orchestrator,
                inbox_size=50,
            )
            await bot.start()
            bots[name] = bot
            skills_str = ", ".join([s.value for s in skills]) if skills else "none"
            logger.info(
                f"Started bot: {name} (role: {role.value}, skills: {skills_str})"
            )
        except Exception as e:
            logger.error(f"Failed to start bot {name}: {e}")

    app.state.ui_bridge = ui_bridge
    app.state.bots = bots
    app.state.world = world
    app.state.bank_actor = bank_actor
    app.state.orchestrator = orchestrator
    app.state.logger = logger
    app.state.account_name = account_name
    app.state.token = token

    logger.info("Bot Manager is running on http://localhost:5173")
    yield

    for bot in bots.values():
        await bot.stop()
    if orchestrator:
        await orchestrator.stop()
    if bank_actor:
        await bank_actor.stop()
    if ui_bridge:
        await ui_bridge.stop()
    logger.info("Bot Manager shutdown complete")


app, rt = fast_app(
    hdrs=(
        *Theme.rose.headers(mode="dark"),
        Script(src="https://unpkg.com/htmx-ext-sse@2.2.3/sse.js"),
    ),
    lifespan=lifespan,
)


@rt
async def index(app, req):
    response = await app.state.ui_bridge.ask(GetStateMessage())
    page_content = DashboardPage(response.state, app.state.world)

    # If htmx request, return just content
    if req.headers.get("HX-Request"):
        return page_content

    # Full page load: wrap with SSE connection
    return Title("Botman"), Body(
        page_content,
        hx_ext="sse",
        sse_connect="/events",
        id="app-body",
        cls="bg-gray-600",
    )


@rt
async def events(app):
    async def event_generator():
        subscriber_queue = asyncio.Queue()

        # Subscribe to updates
        await app.state.ui_bridge.ask(SubscribeMessage(queue=subscriber_queue))
        app.state.logger.info(
            f"SSE: Client connected. Active: {len(app.state.ui_bridge.subscribers)}"
        )

        try:
            # Send initial connection message
            yield "data: Connected\n\n"

            # Stream updates
            while True:
                event_type, data = await subscriber_queue.get()

                if event_type == "bot_changed":
                    bot_name = data["bot_name"]
                    bot_state = data["data"]
                    map_tile = None
                    if bot_state.get("character"):
                        character = bot_state["character"]
                        map_tile = app.state.world.map_for_character(character)
                    app.state.logger.debug(f"SSE: Sending bot_changed_{bot_name} event")
                    yield sse_message(
                        BotCard(bot_name, bot_state, map_tile),
                        event=f"bot_changed_{bot_name}",
                    )

                elif event_type == "log":
                    from botman.web.components import LogEntry

                    app.state.logger.debug(
                        f"SSE: Sending log event from {data.get('source', 'unknown')}"
                    )
                    yield sse_message(LogEntry(data), event="log")

        finally:
            # Always cleanup on disconnect
            await app.state.ui_bridge.ask(UnsubscribeMessage(queue=subscriber_queue))
            app.state.logger.info(
                f"SSE: Client disconnected. Active: {len(app.state.ui_bridge.subscribers)}"
            )

    return EventStream(event_generator())


@rt("/bot_task")
async def post(app, req):
    """Handle task creation from web UI"""
    # Get form data
    form_data = await req.form()
    form_dict = dict(form_data)

    bot_name = form_dict.get("bot_name")
    task_type = form_dict.get("task_type")

    app.state.logger.info(
        f"bot_task called: bot={bot_name}, type={task_type}, params={form_dict}"
    )

    if not bot_name or bot_name not in app.state.bots:
        app.state.logger.error(f"Bot {bot_name} not found")
        return ""

    bot = app.state.bots[bot_name]

    try:
        # Extract task parameters (exclude bot_name and task_type)
        task_params = {
            k: v for k, v in form_dict.items() if k not in ("bot_name", "task_type")
        }

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

        app.state.logger.info(
            f"Creating {task_type} task for {bot_name}: {task.description()}"
        )
        await bot.tell(TaskCreateMessage(task=task))
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
            P(
                "All items in inventory will be deposited",
                cls="text-sm text-gray-400 italic",
            ),
            cls="mt-4",
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
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
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
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
                ),
            ),
            cls="space-y-4",
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


@rt("/bot_toggle_autonomous")
async def bot_toggle_autonomous(app, req):
    """Toggle autonomous mode for a bot"""
    form_data = await req.form()
    bot_name = form_data.get("bot_name")
    enabled = form_data.get("enabled", "false").lower() == "true"

    if bot_name not in app.state.bots:
        return ""

    bot = app.state.bots[bot_name]
    await bot.tell(SetAutonomousModeMessage(enabled=enabled))
    app.state.logger.info(f"Bot {bot_name} autonomous mode set to {enabled}")
    return ""


@rt("/character/{bot_name}")
async def character(app, req, bot_name: str):
    response = await app.state.ui_bridge.ask(GetStateMessage())
    bot_state = response.state["bots"].get(bot_name)

    if not bot_state:
        return Div("Character not found", A("Back to Dashboard", href="/"))

    page_content = CharacterDetailPage(bot_name, bot_state)

    # If htmx request, return just content
    if req.headers.get("HX-Request"):
        return page_content

    # Full page load: wrap with SSE connection
    return Title(f"{bot_name} - Bot Manager"), Body(
        page_content,
        hx_ext="sse",
        sse_connect="/events",
        id="app-body",
        cls="bg-gray-600",
    )


# ===== MRP Production Planning Routes =====


@rt("/production")
async def production(app, req):
    """Production planning page."""
    # Get craftable items
    items_response = await app.state.orchestrator.ask(ListCraftableItemsRequest())
    craftable_items = items_response.items

    # Get current plan status
    plan_response = await app.state.orchestrator.ask(GetPlanStatusRequest())

    page_content = Div(
        # Header
        Div(
            H1("Production Planning", cls="text-2xl font-bold text-white mb-2"),
            P(
                "Create multi-bot production plans using Material Requirements Planning (MRP)",
                cls="text-gray-400",
            ),
            A("← Back to Dashboard", href="/", cls="text-blue-400 hover:text-blue-300"),
            cls="mb-6",
        ),
        # Create Plan Form
        Card(
            H2("Create Production Plan", cls="text-xl font-semibold text-white mb-4"),
            Form(
                Div(
                    Label("Item to Craft", cls="text-sm text-gray-400 mb-1 block"),
                    Select(
                        *[
                            Option(item["name"], value=item["code"])
                            for item in craftable_items
                        ],
                        name="item_code",
                        required=True,
                        cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
                    ),
                    cls="mb-4",
                ),
                Div(
                    Label("Quantity", cls="text-sm text-gray-400 mb-1 block"),
                    Input(
                        type="number",
                        name="quantity",
                        value="10",
                        min="1",
                        required=True,
                        cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
                    ),
                    cls="mb-4",
                ),
                Button(
                    "Create Plan",
                    type="submit",
                    cls="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-md transition-colors",
                ),
                hx_post="/production/create",
                hx_target="#plan-status",
                hx_swap="outerHTML",
                cls="space-y-4",
            ),
            cls="mb-6",
        ),
        # Plan Status
        Div(id="plan-status", *_render_plan_status(plan_response)),
        cls="max-w-6xl mx-auto p-6",
    )

    if req.headers.get("HX-Request"):
        return page_content

    return Title("Production Planning"), Body(
        page_content,
        hx_ext="sse",
        sse_connect="/events",
        id="app-body",
        cls="bg-gray-600",
    )


@rt("/production/create")
async def production_create(app, req):
    """Create a new production plan."""
    form_data = await req.form()
    item_code = form_data.get("item_code")
    quantity = int(form_data.get("quantity", 1))

    app.state.logger.info(f"Creating production plan: {item_code} x{quantity}")

    response = await app.state.orchestrator.ask(
        CreatePlanRequest(item_code=item_code, quantity=quantity)
    )

    # Get updated plan status
    plan_response = await app.state.orchestrator.ask(GetPlanStatusRequest())

    return Div(id="plan-status", *_render_plan_status(plan_response, response))


@rt("/production/status")
async def production_status(app):
    """Get current plan status (for polling)."""
    plan_response = await app.state.orchestrator.ask(GetPlanStatusRequest())
    return Div(id="plan-status", *_render_plan_status(plan_response))


def _render_plan_status(plan_response, create_response=None):
    """Helper to render plan status."""
    elements = []

    # Show creation result if available
    if create_response:
        if create_response.success:
            elements.append(
                Div(
                    P(
                        f"✓ Plan created: {create_response.total_jobs} jobs across {create_response.levels} dependency levels",
                        cls="text-green-400",
                    ),
                    cls="bg-green-900/20 border border-green-500 rounded-md p-4 mb-4",
                )
            )
        else:
            elements.append(
                Div(
                    P(
                        f"✗ Error: {create_response.error or 'Unknown error'}",
                        cls="text-red-400",
                    ),
                    cls="bg-red-900/20 border border-red-500 rounded-md p-4 mb-4",
                )
            )

    if not plan_response.active:
        elements.append(
            Card(P("No active production plan", cls="text-gray-400 text-center py-8"))
        )
        return elements

    # Active plan
    plan_id = plan_response.plan_id
    goal_item = plan_response.goal_item
    goal_quantity = plan_response.goal_quantity
    progress = plan_response.progress
    is_complete = plan_response.is_complete
    jobs_by_status = plan_response.jobs_by_status

    elements.append(
        Card(
            H2("Active Production Plan", cls="text-xl font-semibold text-white mb-4"),
            Div(
                Div(
                    Span("Goal: ", cls="text-gray-400"),
                    Span(f"{goal_item} x{goal_quantity}", cls="text-white font-medium"),
                ),
                Div(
                    Span("Plan ID: ", cls="text-gray-400"),
                    Span(plan_id, cls="text-white font-mono text-sm"),
                ),
                Div(
                    Span("Progress: ", cls="text-gray-400"),
                    Span(progress, cls="text-white font-medium"),
                    Span(
                        " ✓ Complete" if is_complete else "", cls="text-green-400 ml-2"
                    ),
                ),
                cls="space-y-2 mb-6",
            ),
            # Jobs by status
            Div(
                H3("Jobs", cls="text-lg font-semibold text-white mb-3"),
                *_render_jobs_by_status(jobs_by_status),
                cls="space-y-4",
            ),
            # Refresh button
            Button(
                "Refresh Status",
                hx_get="/production/status",
                hx_target="#plan-status",
                hx_swap="outerHTML",
                cls="mt-4 bg-gray-700 hover:bg-gray-600 text-white py-2 px-4 rounded-md text-sm",
            ),
        )
    )

    return elements


def _render_jobs_by_status(jobs_by_status):
    """Render job lists organized by status."""
    elements = []

    status_colors = {
        "completed": ("bg-green-900/20 border-green-600", "text-green-400"),
        "in_progress": ("bg-blue-900/20 border-blue-600", "text-blue-400"),
        "claimed": ("bg-yellow-900/20 border-yellow-600", "text-yellow-400"),
        "pending": ("bg-gray-800 border-gray-600", "text-gray-400"),
        "failed": ("bg-red-900/20 border-red-600", "text-red-400"),
    }

    for status, jobs in jobs_by_status.items():
        if not jobs:
            continue

        bg_color, text_color = status_colors.get(
            status, ("bg-gray-800 border-gray-600", "text-gray-400")
        )

        elements.append(
            Div(
                Div(
                    Span(
                        status.replace("_", " ").title(),
                        cls=f"font-medium {text_color}",
                    ),
                    Span(f"({len(jobs)})", cls="text-gray-500 ml-1"),
                    cls="text-sm font-semibold mb-2",
                ),
                Div(*[_render_job_item(job) for job in jobs], cls="space-y-1"),
                cls=f"{bg_color} border rounded-md p-3",
            )
        )

    return elements


def _render_job_item(job):
    """Render a single job item."""
    claimed_info = f" (by {job['claimed_by']})" if job.get("claimed_by") else ""
    deps_info = f" | deps: {len(job['depends_on'])}" if job["depends_on"] else ""

    return Div(
        Span(f"{job['type']}: ", cls="text-gray-500 text-xs"),
        Span(
            f"{job['item_code']} x{job['quantity']}", cls="text-white text-sm font-mono"
        ),
        Span(claimed_info, cls="text-gray-400 text-xs"),
        Span(deps_info, cls="text-gray-500 text-xs"),
        cls="text-sm",
    )


# ===== Achievements Routes =====

# In-memory storage for selected achievements (for now)
# TODO: Move to SQLite database for persistence
selected_achievements = set()


@rt("/achievements")
async def achievements(app, req):
    """Achievements page"""
    # Fetch all achievements from API
    async with ArtifactsClient(app.state.token) as api:
        # Get all achievements with account progress
        all_achievements = []
        page = 1
        while True:
            achievement_page = await api.get_account_achievements(
                account=app.state.account_name, page=page, size=100
            )
            all_achievements.extend(achievement_page.data)
            if page >= achievement_page.pages:
                break
            page += 1

    # Convert to dicts for easier handling in components
    achievements_list = []
    for ach in all_achievements:
        achievements_list.append(
            {
                "name": ach.name,
                "code": ach.code,
                "description": ach.description,
                "points": ach.points,
                "type": ach.type,
                "target": ach.target,
                "total": ach.total,
                "current": ach.current,
                "completed_at": ach.completed_at,
            }
        )

    # Default: show all achievements
    page_content = AchievementsPage(achievements_list, selected_achievements, achievements_list)

    # If htmx request, return just content
    if req.headers.get("HX-Request"):
        return page_content

    # Full page load: wrap with SSE connection
    return Title("Achievements - Bot Manager"), Body(
        page_content,
        hx_ext="sse",
        sse_connect="/events",
        id="app-body",
        cls="bg-gray-600",
    )


@rt("/achievements/filter")
async def achievements_filter(app, type: str = "all"):
    """Filter achievements by type - returns just the grid content"""
    # Fetch all achievements from API
    async with ArtifactsClient(app.state.token) as api:
        all_achievements = []
        page = 1
        while True:
            achievement_page = await api.get_account_achievements(
                account=app.state.account_name, page=page, size=100
            )
            all_achievements.extend(achievement_page.data)
            if page >= achievement_page.pages:
                break
            page += 1

    # Convert to dicts
    achievements_list = []
    for ach in all_achievements:
        achievements_list.append(
            {
                "name": ach.name,
                "code": ach.code,
                "description": ach.description,
                "points": ach.points,
                "type": ach.type,
                "target": ach.target,
                "total": ach.total,
                "current": ach.current,
                "completed_at": ach.completed_at,
            }
        )

    # Filter by type if requested
    if type != "all":
        filtered = [ach for ach in achievements_list if ach["type"] == type]
    else:
        filtered = achievements_list

    from botman.web.components import AchievementCard
    # Return just the grid content
    return Grid(
        *[
            AchievementCard(ach, ach["code"] in selected_achievements)
            for ach in filtered
        ],
        cols=1,
        cols_md=2,
        cols_lg=3,
        gap=4,
    )


@rt("/achievements/toggle")
async def achievements_toggle(app, req):
    """Toggle achievement selection and return updated page"""
    form_data = await req.form()
    code = form_data.get("code")

    if code:
        if code in selected_achievements:
            selected_achievements.remove(code)
            app.state.logger.info(f"Deselected achievement: {code}")
        else:
            selected_achievements.add(code)
            app.state.logger.info(f"Selected achievement: {code}")

    # Fetch all achievements and return updated page
    async with ArtifactsClient(app.state.token) as api:
        all_achievements = []
        page = 1
        while True:
            achievement_page = await api.get_account_achievements(
                account=app.state.account_name, page=page, size=100
            )
            all_achievements.extend(achievement_page.data)
            if page >= achievement_page.pages:
                break
            page += 1

    # Convert to dicts
    achievements_list = []
    for ach in all_achievements:
        achievements_list.append(
            {
                "name": ach.name,
                "code": ach.code,
                "description": ach.description,
                "points": ach.points,
                "type": ach.type,
                "target": ach.target,
                "total": ach.total,
                "current": ach.current,
                "completed_at": ach.completed_at,
            }
        )

    # Return full page content
    return AchievementsPage(achievements_list, selected_achievements, achievements_list)
