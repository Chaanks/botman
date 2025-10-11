from fasthtml.common import *
from monsterui.all import *


def TaskFormFields(task_type: str, bot_name: str):
    """Generate dynamic form fields based on task type."""

    if task_type == "gather":
        return Div(
            Div(
                Label("Resource Code", cls="text-sm text-gray-400 mb-1 block"),
                Input(
                    type="text",
                    name="resource_code",
                    placeholder="e.g., copper_rocks, ash_tree",
                    required=True,
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                ),
                P("The code of the resource to gather", cls="text-xs text-gray-500 mt-1")
            ),
            Div(
                Label("Target Amount", cls="text-sm text-gray-400 mb-1 block"),
                Input(
                    type="number",
                    name="target_amount",
                    placeholder="10",
                    value="10",
                    min="1",
                    required=True,
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                ),
                P("How many resources to gather", cls="text-xs text-gray-500 mt-1")
            ),
            cls="space-y-4"
        )

    elif task_type == "deposit":
        return Div(
            Div(
                Label("Deposit Mode", cls="text-sm text-gray-400 mb-1 block"),
                Select(
                    Option("Single Item", value="single"),
                    Option("All Inventory", value="all"),
                    name="deposit_mode",
                    id="deposit_mode",
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
                    hx_get=f"/deposit_mode_fields?bot_name={bot_name}",
                    hx_target="#deposit-fields",
                    hx_swap="innerHTML",
                    hx_trigger="change"
                ),
                P("Choose what to deposit", cls="text-xs text-gray-500 mt-1")
            ),
            Div(
                # Single item fields by default
                Div(
                    Label("Item Code", cls="text-sm text-gray-400 mb-1 block"),
                    Input(
                        type="text",
                        name="item_code",
                        placeholder="e.g., copper_ore, ash_wood",
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
                        cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    ),
                ),
                id="deposit-fields",
                cls="space-y-4 mt-4"
            ),
            cls="space-y-4"
        )

    elif task_type == "craft":
        return Div(
            Div(
                Label("Item Code", cls="text-sm text-gray-400 mb-1 block"),
                Input(
                    type="text",
                    name="item_code",
                    placeholder="e.g., copper_dagger, wooden_staff",
                    required=True,
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                ),
                P("The code of the item to craft", cls="text-xs text-gray-500 mt-1")
            ),
            Div(
                Label("Target Amount", cls="text-sm text-gray-400 mb-1 block"),
                Input(
                    type="number",
                    name="target_amount",
                    placeholder="10",
                    value="1",
                    min="1",
                    required=True,
                    cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                ),
                P("How many items to craft", cls="text-xs text-gray-500 mt-1")
            ),
            Div(
                Label(
                    Input(
                        type="checkbox",
                        name="recycle",
                        value="true",
                        cls="mr-2"
                    ),
                    "Recycle after crafting",
                    cls="text-sm text-gray-400 flex items-center cursor-pointer"
                ),
                P("Automatically recycle crafted items for materials", cls="text-xs text-gray-500 mt-1 ml-6")
            ),
            cls="space-y-4"
        )

    return Div(P("Select a task type", cls="text-sm text-gray-400"))


def StatusBadge(status: str):
    """Compact status badge using FrankenUI Label"""
    label_type = {
        "Idle": LabelT.secondary,
        "Ready": LabelT.primary,
        "Busy": LabelT.primary,
        "Cooldown": LabelT.destructive,
        "Error": LabelT.destructive,
    }
    return Label(status, cls=label_type.get(status, LabelT.secondary))


def CompactStat(label: str, value: str):
    """Single compact stat display"""
    return Div(
        P(label, cls=TextPresets.muted_sm),
        P(value, cls=(TextT.sm, TextT.medium)),
        cls="space-y-1"
    )


def ProgressBar(label: str, current: int, max_val: int, color: str = "bg-green-500"):
    """Progress bar component"""
    percentage = (current / max_val * 100) if max_val > 0 else 0

    return Div(
        Div(
            Span(label, cls="text-xs text-gray-400"),
            Span(f"{current}/{max_val}", cls="text-xs text-gray-300"),
            cls="flex justify-between mb-1"
        ),
        Div(
            Div(
                style=f"width: {percentage}%",
                cls=f"{color} h-full rounded-full transition-all duration-300"
            ),
            cls="w-full bg-gray-700 rounded-full h-2"
        ),
        cls="w-full"
    )


def MapDisplay(character, map_tile):
    """Map display component showing current location"""
    if not map_tile:
        return Div(cls="w-28 h-28 rounded-lg bg-gray-800/30")

    return Div(
        Img(
            src=f"https://artifactsmmo.com/images/maps/{map_tile.skin}.png",
            alt="Map",
            cls="absolute inset-0 w-full h-full object-cover",
            onerror="this.src='https://artifactsmmo.com/images/maps/default.png'"
        ),
        cls="relative w-28 h-28 overflow-hidden rounded-lg bg-gray-800/30"
    )


def BotCard(bot_name: str, bot_state: dict, map_tile=None):
    """Redesigned bot card with dark theme, character skin, and map display"""
    status = bot_state.get("status", "Unknown")
    current_task = bot_state.get("current_task")
    progress = bot_state.get("progress", "0/0")
    character = bot_state.get("character")
    queue_size = bot_state.get("queue_size", 0)

    # Extract character data
    if character:
        level = character.level
        gold = character.gold
        cooldown = int(character.ready_in())
        hp = character.stats.hp
        max_hp = character.stats.max_hp
        xp = character.xp
        max_xp = character.max_xp
        skin = character.skin
        x, y = character.position.x, character.position.y
        account = character.account
    else:
        level = 1
        gold = 0
        cooldown = 0
        hp = max_hp = 100
        xp = max_xp = 100
        skin = "default"
        x = y = 0
        account = "Unknown"

    cooldown_text = f"{cooldown}s" if cooldown > 0 else "Ready"
    task_display = current_task if current_task else "Idle"
    if current_task and progress != "0/0":
        task_display = f"{current_task} ({progress})"

    map_name = map_tile.name if map_tile else "Unknown"

    return Card(
        # Main content wrapper
        Div(
            # Map display - floating top right
            Div(
                MapDisplay(character, map_tile) if character else None,
                cls="absolute right-4 top-10 z-10"
            ),

            # Main content column
            Div(
                # Status Row
                Div(
                    StatusBadge(status),
                    Button(
                        UkIcon("refresh-cw", height=16),
                        hx_post="/bot_restart",
                        hx_vals=f'{{"bot_name": "{bot_name}"}}',
                        hx_swap="none",
                        cls="p-1 hover:text-gray-200 text-gray-400 transition-colors ml-2",
                        title="Refresh"
                    ),
                    cls="flex items-center gap-x-2 h-8 mb-2"
                ),

                # Character Info Section
                Div(
                    Div(
                        H2(bot_name, cls="text-xl font-bold text-white"),
                        Img(
                            src=f"https://artifactsmmo.com/images/characters/{skin}.png",
                            alt="Character",
                            cls="w-6 h-6 object-contain",
                            onerror="this.src='https://artifactsmmo.com/images/characters/default.png'"
                        ) if character else None,
                        cls="flex items-center gap-2"
                    ),
                    Div(f"Account: {account}", cls="text-sm text-gray-400 mt-2 mb-1") if character else None,
                    Div(f"Level {level}", cls="text-sm text-gray-400 mb-2") if character else None,
                    Div(
                        Span(f"Gold {gold:,}", cls="text-sm text-gray-400"),
                        cls="flex items-center gap-2 mb-4"
                    ) if character else None,
                    cls="h-32 flex flex-col justify-center mb-2 mt-4"
                ),

                # Progress Bars Section
                Div(
                    ProgressBar("HP", hp, max_hp, "bg-red-500"),
                    ProgressBar("XP", xp, max_xp, "bg-green-500"),
                    cls="space-y-2 mb-4"
                ) if character else None,

                # Stats Grid
                Grid(
                    # Cooldown with client-side countdown
                    Div(
                        Div(
                            UkIcon("timer", height=16, cls="text-blue-400"),
                            Span("Cooldown", cls="text-sm text-gray-400"),
                            cls="flex items-center gap-2"
                        ),
                        Div(
                            cooldown_text,
                            cls="text-white mt-1",
                            id=f"cooldown-{bot_name}",
                            data_cooldown=str(cooldown)
                        ),
                        cls="flex flex-col justify-center"
                    ),

                    # Location
                    Div(
                        Div(
                            UkIcon("map-pin", height=16, cls="text-emerald-400"),
                            Span("Location", cls="text-sm text-gray-400"),
                            cls="flex items-center gap-2 mt-2"
                        ),
                        Div(f"{x}, {y}", cls="text-white mt-1"),
                        Div(map_name, cls="text-xs text-gray-500"),
                        cls="flex flex-col justify-center"
                    ),

                    cols=2,
                    gap=2,
                    cls="mt-2"
                ) if character else None,

                # Task info
                Div(
                    P(Strong("Task:"), f" {task_display}", cls="text-sm text-gray-300"),
                    P(f"{queue_size} queued", cls="text-xs text-gray-500") if queue_size > 0 else None,
                    cls="mt-4 space-y-1"
                ),

                cls="flex flex-col h-full"
            ),

            # Error display
            Div(
                bot_state.get("error"),
                cls="text-red-500 mt-2 text-sm bg-red-500/10 p-2 rounded"
            ) if bot_state.get("error") else None,

            cls="p-4 pt-1 relative h-full"
        ),

        # Footer with actions
        footer=Div(
            A(
                "Details",
                href=f"/character/{bot_name}",
                hx_get=f"/character/{bot_name}",
                hx_target="#main-content",
                hx_swap="outerHTML",
                cls="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium rounded-md transition-colors"
            ),
            # Button(
            #     UkIcon("x", height=16),
            #     hx_post="/bot_clear_queue",
            #     hx_vals=f'{{"bot_name": "{bot_name}"}}',
            #     hx_swap="none",
            #     cls=(ButtonT.destructive, ButtonT.sm),
            #     title="Clear Queue"
            # ),
            cls="flex justify-center"
        ),

        id=f"bot-{bot_name}",
        sse_swap=f"bot_changed_{bot_name}",
        hx_swap="outerHTML swap:0ms settle:0ms",
        cls="bg-gray-800/90 border-0"
    )


def LogEntry(log: dict):
    """Chat-like log entry without background boxes"""
    level = log.get("level", "INFO")
    source = log.get("source", "system")
    message = log.get("message", "")

    # Color mapping for log levels
    level_config = {
        "INFO": {"color": "text-blue-400"},
        "WARNING": {"color": "text-yellow-400"},
        "ERROR": {"color": "text-red-400"},
        "CRITICAL": {"color": "text-red-500"},
        "DEBUG": {"color": "text-gray-500"},
    }

    config = level_config.get(level, level_config["INFO"])

    return Div(
        Span(f"[{source}]", cls="text-xs font-medium text-gray-500"),
        Span(level, cls=f"text-xs font-semibold {config['color']} ml-2"),
        Span(message, cls="text-sm text-gray-300 ml-3"),
        cls="flex items-baseline py-1.5 hover:bg-gray-700/30 px-2 -mx-2 rounded transition-colors"
    )


def LogsSection(logs: list):
    """Clean logs section with dark theme"""
    recent_logs = logs[-50:][::-1]

    return Card(
        Div(
            *[LogEntry(log) for log in recent_logs] if recent_logs else [
                Div(
                    UkIcon("file-text", height=32, cls="text-gray-600 mb-2"),
                    P("No logs yet", cls="text-sm text-gray-500"),
                    cls="flex flex-col items-center justify-center py-12"
                )
            ],
            id="logs-container",
            sse_swap="log",
            hx_swap="afterbegin",
            cls="space-y-2 max-h-[40rem] overflow-y-auto p-4"
        ),
        header=Div(
            H3("Logs", cls="text-lg font-semibold text-white"),
            Div(
                Span(str(len(recent_logs)), cls="text-sm font-bold text-blue-400"),
                Span("entries", cls="text-sm text-gray-500 ml-1"),
                cls="flex items-center"
            ),
            cls="flex items-center justify-between"
        ),
        cls="bg-gray-800/90 border-gray-700/50"
    )


def DashboardPage(state: dict, world=None):
    """Compact dashboard with 2 rows of bot cards and logs below"""
    bots = state.get("bots", {})
    logs = state.get("logs", [])

    # Count bot statuses for header
    status_counts = {}
    for bot_state in bots.values():
        status = bot_state.get("status", "Unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    status_text = " • ".join([f"{count} {status.lower()}" for status, count in status_counts.items()])

    # Create bot cards with map tiles
    bot_cards = []
    for name, bot_state in bots.items():
        map_tile = None
        if world and bot_state.get("character"):
            character = bot_state["character"]
            map_tile = world.map_for_character(character)
        bot_cards.append(BotCard(name, bot_state, map_tile))

    return Container(
        Div(
            Grid(
                *bot_cards,
                cols=3,
                gap=4,
            ),
            cls="mb-8 mt-4"
        ),

        # Logs section
        LogsSection(logs),

        # Client-side cooldown countdown script
        Script("""
        (function() {
            function updateCooldowns() {
                document.querySelectorAll('[data-cooldown]').forEach(el => {
                    let cooldown = parseInt(el.dataset.cooldown);
                    if (cooldown > 0) {
                        cooldown--;
                        el.dataset.cooldown = cooldown;
                        el.textContent = cooldown > 0 ? cooldown + 's' : 'Ready';
                    }
                });
            }

            // Update every second
            setInterval(updateCooldowns, 1000);

            // Also update when SSE swaps occur (HTMX reinitializes elements)
            document.body.addEventListener('htmx:afterSwap', function(evt) {
                if (evt.detail.target.id && evt.detail.target.id.startsWith('bot-')) {
                    // New bot card swapped in, cooldown will be in data attribute
                }
            });
        })();
        """),

        cls=ContainerT.xl,
        id="main-content"
    )


def CharacterDetailHeader(bot_name, character, status):
    """Modern header for character detail page with dark theme"""
    return Div(
        # Back button
        A(
            UkIcon("arrow-left", height=18, cls="text-gray-400"),
            Span("Back to Dashboard", cls="text-sm text-gray-400 ml-2"),
            href="/",
            hx_get="/",
            hx_target="#main-content",
            hx_swap="outerHTML",
            cls="inline-flex items-center hover:text-gray-300 transition-colors mb-6"
        ),

        # Character header
        Div(
            # Character avatar and name
            Div(
                Img(
                    src=f"https://artifactsmmo.com/images/characters/{character.skin}.png",
                    alt=bot_name,
                    cls="w-16 h-16 object-contain",
                    onerror="this.src='https://artifactsmmo.com/images/characters/default.png'"
                ),
                Div(
                    H1(bot_name, cls="text-3xl font-bold text-white"),
                    Div(
                        Span(f"Level {character.level}", cls="text-gray-400 text-sm"),
                        Span("•", cls="text-gray-600 mx-2"),
                        StatusBadge(status),
                        cls="flex items-center mt-1"
                    ),
                    cls="ml-4"
                ),
                cls="flex items-center"
            ),
            cls="bg-gray-800/90 rounded-lg p-6 mb-6"
        ),
        cls="mb-6"
    )


def CharacterDetailPage(bot_name: str, bot_state: dict):
    """Modern character detail page with dark theme"""
    status = bot_state.get("status", "Unknown")
    current_task = bot_state.get("current_task")
    progress = bot_state.get("progress", "0/0")
    character = bot_state.get("character")
    queue_size = bot_state.get("queue_size", 0)

    if not character:
        return Container(
            H2("Character Not Found", cls="text-white"),
            A("← Back to Dashboard", href="/", hx_get="/", hx_target="#main-content", hx_swap="outerHTML", cls="text-blue-400 hover:text-blue-300"),
        )

    # Task display
    task_display = current_task if current_task else "No active task"
    if current_task and progress != "0/0":
        task_display = f"{current_task} ({progress})"

    cooldown = int(character.ready_in())
    cooldown_text = f"{cooldown}s" if cooldown > 0 else "Ready"

    return Container(
        CharacterDetailHeader(bot_name, character, status),

        Grid(
            # Left column: Character Stats
            Div(
                # Overview Card
                Div(
                    H3("Overview", cls="text-lg font-semibold text-white mb-4"),

                    # Progress Bars
                    Div(
                        ProgressBar("HP", character.stats.hp, character.stats.max_hp, "bg-red-500"),
                        ProgressBar("XP", character.xp, character.max_xp, "bg-green-500"),
                        cls="space-y-3 mb-4"
                    ),

                    # Quick Stats Grid
                    Grid(
                        Div(
                            Div(
                                UkIcon("coins", height=16, cls="text-yellow-400"),
                                Span("Gold", cls="text-xs text-gray-400 ml-1"),
                                cls="flex items-center mb-1"
                            ),
                            P(f"{character.gold:,}", cls="text-white font-medium"),
                        ),
                        Div(
                            Div(
                                UkIcon("timer", height=16, cls="text-blue-400"),
                                Span("Cooldown", cls="text-xs text-gray-400 ml-1"),
                                cls="flex items-center mb-1"
                            ),
                            P(cooldown_text, cls="text-white font-medium"),
                        ),
                        Div(
                            Div(
                                UkIcon("map-pin", height=16, cls="text-emerald-400"),
                                Span("Position", cls="text-xs text-gray-400 ml-1"),
                                cls="flex items-center mb-1"
                            ),
                            P(f"({character.position.x}, {character.position.y})", cls="text-white font-medium"),
                        ),
                        Div(
                            Div(
                                UkIcon("zap", height=16, cls="text-purple-400"),
                                Span("Speed", cls="text-xs text-gray-400 ml-1"),
                                cls="flex items-center mb-1"
                            ),
                            P(str(character.speed), cls="text-white font-medium"),
                        ),
                        cols=2,
                        gap=4,
                    ),
                    cls="bg-gray-800/90 rounded-lg p-6"
                ),

                # Combat Stats Card
                Div(
                    H3("Combat Stats", cls="text-lg font-semibold text-white mb-4"),
                    Grid(
                        Div(
                            Div(
                                UkIcon("crosshair", height=16, cls="text-red-400"),
                                Span("Attack", cls="text-xs text-gray-400 ml-1"),
                                cls="flex items-center mb-1"
                            ),
                            P(str(character.stats.total_attack()), cls="text-white font-medium text-xl"),
                        ),
                        Div(
                            Div(
                                UkIcon("sword", height=16, cls="text-orange-400"),
                                Span("Damage", cls="text-xs text-gray-400 ml-1"),
                                cls="flex items-center mb-1"
                            ),
                            P(str(character.stats.total_damage()), cls="text-white font-medium text-xl"),
                        ),
                        Div(
                            Div(
                                UkIcon("shield", height=16, cls="text-blue-400"),
                                Span("Resistance", cls="text-xs text-gray-400 ml-1"),
                                cls="flex items-center mb-1"
                            ),
                            P(str(character.stats.total_resistance()), cls="text-white font-medium text-xl"),
                        ),
                        cols=3,
                        gap=4,
                    ),
                    cls="bg-gray-800/90 rounded-lg p-6 mt-4"
                ),
                cls="space-y-4"
            ),

            # Right column: Tasks & Actions
            Div(
                # Current Task Card
                Div(
                    H3("Current Task", cls="text-lg font-semibold text-white mb-4"),
                    Div(
                        P(task_display, cls="text-gray-300"),
                        P(f"{queue_size} tasks in queue", cls="text-xs text-gray-500 mt-2") if queue_size > 0 else None,
                    ),
                    cls="bg-gray-800/90 rounded-lg p-6"
                ),

                # Add Task Form
                Div(
                    H3("Add New Task", cls="text-lg font-semibold text-white mb-4"),
                    Form(
                        Div(
                            Label("Task Type", cls="text-sm text-gray-400 mb-1 block"),
                            Select(
                                Option("Gather Resource", value="gather"),
                                Option("Deposit Items", value="deposit"),
                                Option("Craft Items", value="craft"),
                                name="task_type",
                                id="task_type",
                                cls="w-full bg-gray-700 text-white border border-gray-600 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
                                hx_get=f"/task_form_fields?bot_name={bot_name}",
                                hx_target="#task-params-container",
                                hx_swap="innerHTML",
                                hx_trigger="change"
                            ),
                        ),
                        Div(
                            # Dynamic fields will be loaded here based on task type
                            TaskFormFields("gather", bot_name),
                            id="task-params-container",
                            cls="space-y-4"
                        ),
                        Button(
                            "Add Task",
                            type="submit",
                            cls="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-md transition-colors mt-4"
                        ),
                        Input(type="hidden", name="bot_name", value=bot_name),
                        hx_post="/bot_task",
                        hx_swap="none",
                        cls="space-y-4"
                    ),
                    cls="bg-gray-800/90 rounded-lg p-6 mt-4"
                ),

                # Actions Card
                Div(
                    H3("Actions", cls="text-lg font-semibold text-white mb-4"),
                    Div(
                        Button(
                            UkIcon("refresh-cw", height=16, cls="mr-2"),
                            "Restart Bot",
                            hx_post="/bot_restart",
                            hx_vals=f'{{"bot_name": "{bot_name}"}}',
                            hx_swap="none",
                            cls="flex-1 bg-gray-700 hover:bg-gray-600 text-white font-medium py-2 px-4 rounded-md transition-colors flex items-center justify-center"
                        ),
                        Button(
                            UkIcon("trash-2", height=16, cls="mr-2"),
                            "Clear Queue",
                            hx_post="/bot_clear_queue",
                            hx_vals=f'{{"bot_name": "{bot_name}"}}',
                            hx_swap="none",
                            cls="flex-1 bg-red-600 hover:bg-red-700 text-white font-medium py-2 px-4 rounded-md transition-colors flex items-center justify-center"
                        ),
                        cls="flex gap-3"
                    ),
                    cls="bg-gray-800/90 rounded-lg p-6 mt-4"
                ),
                cls="space-y-4"
            ),

            cols=1,
            cols_lg=2,
            gap=6,
        ),

        cls=ContainerT.xl,
        id="main-content"
    )
