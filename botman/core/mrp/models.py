from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Set, List
from abc import ABC, abstractmethod
from botman.core.api.models import Position, Skill, CharacterRole
from botman.core.tasks.base import Task
from botman.core.world import World


class JobType(str, Enum):
    GATHER = "gather"
    CRAFT = "craft"
    FIGHT = "fight"


class JobStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job(ABC):
    """Independent unit of work that bots can execute."""

    # Identity
    id: str
    type: JobType

    # Requirements
    required_role: CharacterRole

    # Optional fields (with defaults)
    required_skill: Optional[Skill] = None
    location: Optional[Position] = None
    depends_on: Set[str] = field(default_factory=set)

    # State
    status: JobStatus = JobStatus.PENDING
    claimed_by: Optional[str] = None

    # Bank reservations (for future use)
    material_reservations: List[str] = field(default_factory=list)

    def is_ready(self, completed_jobs: Set[str]) -> bool:
        return self.depends_on.issubset(completed_jobs)

    def matches_bot(self, role: CharacterRole, skills: List[Skill]) -> bool:
        if self.required_role != role:
            return False

        if self.required_skill is None:
            return True

        return self.required_skill in skills

    @abstractmethod
    def to_tasks(self, world: "World") -> List["Task"]:
        """Convert this job into a list of executable tasks."""
        pass

    @abstractmethod
    def description(self) -> str:
        """Human-readable description of this job."""
        pass

    def __repr__(self) -> str:
        deps = f", deps={len(self.depends_on)}" if self.depends_on else ""
        return f"<{self.__class__.__name__} {self.id}{deps}>"


@dataclass
class Goal:
    """A high-level objective that can be decomposed into jobs."""

    plan_id: str
    description: str

    # Jobs organized by dependency level
    jobs_by_level: List[List[Job]] = field(default_factory=list)
    all_jobs: List[Job] = field(default_factory=list)
    completed_job_ids: Set[str] = field(default_factory=set)

    def add_job(self, job: Job, level: int) -> None:
        while len(self.jobs_by_level) <= level:
            self.jobs_by_level.append([])
        self.jobs_by_level[level].append(job)
        self.all_jobs.append(job)

    def get_ready_jobs(self) -> List[Job]:
        return [
            job
            for job in self.all_jobs
            if job.status == JobStatus.PENDING and job.is_ready(self.completed_job_ids)
        ]

    def mark_completed(self, job_id: str) -> None:
        self.completed_job_ids.add(job_id)

    def is_complete(self) -> bool:
        return len(self.completed_job_ids) == len(self.all_jobs)

    def progress_summary(self) -> str:
        return f"{len(self.completed_job_ids)}/{len(self.all_jobs)} jobs"

    def __repr__(self) -> str:
        return f"<Goal {self.plan_id}: {self.description}, {len(self.all_jobs)} jobs>"


# Concrete Job Implementations


@dataclass
class GatherJob(Job):
    """Job for gathering resources from the world."""

    item_code: str = ""
    quantity: int = 0

    def to_tasks(self, world: "World") -> List["Task"]:
        from botman.core.tasks.gather import GatherTask
        from botman.core.tasks.deposit import DepositTask

        resource = world.resource_from_drop(self.item_code)
        if not resource:
            raise ValueError(f"Cannot find resource that drops {self.item_code}")

        return [
            GatherTask(resource_code=resource.code, target_amount=self.quantity),
            DepositTask(deposit_all=True),
        ]

    def description(self) -> str:
        return f"Gather {self.item_code} x{self.quantity}"


@dataclass
class CraftJob(Job):
    """Job for crafting items at workshops."""

    item_code: str = ""
    quantity: int = 0

    def to_tasks(self, world: "World") -> List["Task"]:
        from botman.core.tasks.withdraw import WithdrawTask
        from botman.core.tasks.craft import CraftTask
        from botman.core.tasks.deposit import DepositTask

        item = world.item(self.item_code)
        if not item or not item.craft:
            raise ValueError(
                f"Cannot craft {self.item_code}: item not found or not craftable"
            )

        # Calculate materials needed
        materials_needed = {}
        recipe_output = item.craft.quantity
        crafts_needed = (self.quantity + recipe_output - 1) // recipe_output

        for req in item.craft.requirements:
            materials_needed[req.code] = req.quantity * crafts_needed

        # Create withdraw task for all materials
        withdraw_items = [
            {"code": code, "quantity": qty} for code, qty in materials_needed.items()
        ]

        return [
            WithdrawTask(items=withdraw_items),
            CraftTask(item_code=self.item_code, target_amount=self.quantity),
            DepositTask(deposit_all=True),
        ]

    def description(self) -> str:
        return f"Craft {self.item_code} x{self.quantity}"


@dataclass
class FightJob(Job):
    """Job for fighting monsters."""

    monster_code: str = ""
    kill_count: int = 0

    def to_tasks(self, world: "World") -> List["Task"]:
        from botman.core.tasks.fight import FightTask

        return [FightTask(monster_code=self.monster_code, target_kills=self.kill_count)]

    def description(self) -> str:
        return f"Fight {self.monster_code} x{self.kill_count}"
