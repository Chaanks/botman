from dataclasses import dataclass, asdict
from typing import Dict, Any, List
from botman.core.api.models import CharacterRole, Skill
from botman.core.mrp.models import Job


# Request Messages (Bot -> Orchestrator)


@dataclass
class QueryJobsRequest:
    """Request jobs matching bot's role and skills."""

    role: CharacterRole
    skills: List[Skill]


@dataclass
class ClaimJobRequest:
    """Claim a specific job."""

    job_id: str
    bot_name: str


@dataclass
class CompleteJobRequest:
    """Mark a job as completed."""

    job_id: str
    bot_name: str


@dataclass
class FailJobRequest:
    """Mark a job as failed."""

    job_id: str
    bot_name: str
    error: str


@dataclass
class GetPlanStatusRequest:
    """Get the status of the active production plan."""

    pass


@dataclass
class CreatePlanRequest:
    """Create a new production plan."""

    item_code: str
    quantity: int = 1


@dataclass
class ListCraftableItemsRequest:
    """List all craftable items."""

    pass


# Response Messages (Orchestrator -> Bot)


@dataclass
class QueryJobsResponse:
    """Response containing available jobs."""

    jobs: List["Job"]


@dataclass
class ClaimJobResponse:
    """Response to claim request."""

    success: bool
    error: str = ""


@dataclass
class CompleteJobResponse:
    """Response to complete request."""

    success: bool
    plan_complete: bool = False
    error: str = ""


@dataclass
class FailJobResponse:
    """Response to fail request."""

    success: bool
    status: str = ""
    error: str = ""


@dataclass
class GetPlanStatusResponse:
    """Response with plan status."""

    active: bool
    plan_id: str = ""
    goal_item: str = ""
    goal_quantity: int = 0
    progress: str = ""
    is_complete: bool = False
    total_jobs: int = 0
    jobs_by_status: Dict[str, List[Dict[str, Any]]] = None

    def __post_init__(self):
        if self.jobs_by_status is None:
            self.jobs_by_status = {}


@dataclass
class CreatePlanResponse:
    """Response to plan creation."""

    success: bool
    plan_id: str = ""
    total_jobs: int = 0
    levels: int = 0
    error: str = ""


@dataclass
class ListCraftableItemsResponse:
    """Response with craftable items."""

    items: List[Dict[str, str]]  # [{"code": ..., "name": ...}]


# Utility functions


def to_dict(message) -> Dict[str, Any]:
    """Convert a message dataclass to dict, handling enums."""
    result = asdict(message)

    # Convert enums to values
    for key, value in result.items():
        if hasattr(value, "value"):
            result[key] = value.value
        elif isinstance(value, list):
            result[key] = [v.value if hasattr(v, "value") else v for v in value]

    return result
