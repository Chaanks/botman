"""HTML components for the FastHTML + HTMX dashboard using MonsterUI."""

from fasthtml.common import *
from monsterui.all import *


def StatusLabel(status: str):
    """Render a status label with appropriate styling."""
    label_type = {
        'Idle': LabelT.primary,
        'Ready': LabelT.primary,
        'Busy': LabelT.secondary,
        'Cooldown': LabelT.destructive,
        'Error': LabelT.destructive
    }.get(status, LabelT.primary)

    return Label(status, cls=label_type)


def BotCard(bot_name: str, bot_state: dict):
    """Render a bot status card with live updates via SSE."""
    status = bot_state.get('status', 'Unknown')
    current_task = bot_state.get('current_task')
    progress = bot_state.get('progress', '0/0')
    cooldown = bot_state.get('cooldown', 0)
    character = bot_state.get('character')
    queue_size = bot_state.get('queue_size', 0)

    # Character info
    char_info = f"Level {character.level} | HP: {character.stats.hp}/{character.stats.max_hp}" if character else "Loading..."

    # Card header with bot name and status
    header = DivFullySpaced(
        H3(bot_name),
        StatusLabel(status)
    )

    # Card body content
    body_content = [
        P(char_info, cls=TextPresets.muted_sm),
        Divider(),
        P(Strong("Task: "), current_task or "None"),
    ]

    if current_task:
        body_content.append(P(Strong("Progress: "), progress))
    if queue_size > 0:
        body_content.append(P(Strong("Queue: "), f"{queue_size} tasks"))
    if cooldown > 0:
        body_content.append(P(Strong("Cooldown: "), f"{cooldown}s"))

    # Task form
    task_form = Form(
        DivHStacked(
            Select(
                Option("Gather", value="gather"),
                Option("Bank", value="bank"),
                Option("Fight", value="fight"),
                name="task_type"
            ),
            Input(type="text", name="task_params", placeholder="e.g., copper 10"),
            Input(type="hidden", name="bot_name", value=bot_name),
        ),
        Button("Add Task", type="submit", cls=ButtonT.primary),
        hx_post="/bot_task",
        hx_target=f"#bot-{bot_name}",
        hx_swap="outerHTML",
        cls="space-y-2"
    )

    # Footer with control buttons
    footer = DivHStacked(
        Button(
            "Restart",
            hx_post="/bot_restart",
            hx_vals=f'{{"bot_name": "{bot_name}"}}',
            hx_target=f"#bot-{bot_name}",
            hx_swap="outerHTML",
            cls=ButtonT.secondary
        ),
        Button(
            "Clear Queue",
            hx_post="/bot_clear_queue",
            hx_vals=f'{{"bot_name": "{bot_name}"}}',
            hx_target=f"#bot-{bot_name}",
            hx_swap="outerHTML",
            cls=ButtonT.destructive
        ),
        cls="gap-2"
    )

    return Card(
        *body_content,
        task_form,
        header=header,
        footer=footer,
        id=f"bot-{bot_name}",
        sse_swap=f"bot_changed_{bot_name}",
        hx_swap="outerHTML"
    )


def LogEntry(log: dict):
    """Render a single log entry."""
    level = log.get('level', 'INFO')
    source = log.get('source', 'system')
    message = log.get('message', '')

    # Map log levels to MonsterUI alert types
    alert_type = {
        'INFO': AlertT.info,
        'WARNING': AlertT.warning,
        'ERROR': AlertT.error,
        'DEBUG': AlertT.info
    }.get(level, AlertT.info)

    return Alert(
        Strong(f"[{source}] "),
        message,
        cls=alert_type + " mb-2"
    )


def LogsSection(logs: list):
    """Render the logs section with most recent 50 logs."""
    recent_logs = logs[-50:][::-1]

    return Card(
        H2("System Logs"),
        Divider(),
        Div(
            *[LogEntry(log) for log in recent_logs],
            id="logs-container",
            sse_swap="log",
            hx_swap="afterbegin",
            cls="space-y-2 max-h-96 overflow-y-auto"
        ),
        cls="mt-6"
    )


def DashboardPage(state: dict):
    """Render the main dashboard page with live SSE updates."""
    bots = state.get('bots', {})
    logs = state.get('logs', [])

    return Titled(
        "🤖 Bot Manager Dashboard",
        Grid(
            *[BotCard(name, bot_state) for name, bot_state in bots.items()],
            cols=3
        ),
        LogsSection(logs),
        hx_ext="sse",
        sse_connect="/events"
    )
