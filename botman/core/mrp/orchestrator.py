import logging
from typing import Dict, Any, Optional, List
from functools import singledispatchmethod

from botman.core.actor import Actor
from botman.core.mrp.models import Job, JobStatus, Goal
from botman.core.mrp.planner import (
    CraftGoalPlanner,
    CombatGoalPlanner,
    SkillLevelGoalPlanner,
)
from botman.core.mrp.messages import (
    QueryJobsRequest,
    QueryJobsResponse,
    ClaimJobRequest,
    ClaimJobResponse,
    CompleteJobRequest,
    CompleteJobResponse,
    FailJobRequest,
    FailJobResponse,
    GetPlanStatusRequest,
    GetPlanStatusResponse,
    CreatePlanRequest,
    CreatePlanResponse,
    CreateCombatGoalRequest,
    CreateSkillGoalRequest,
    ListCraftableItemsRequest,
    ListCraftableItemsResponse,
)
from botman.core.world import World

logger = logging.getLogger(__name__)


class JobOrchestrator(Actor):
    """
    Central coordinator for goals and job execution.

    Responsibilities:
    - Create goals from requests (craft, combat, skill leveling)
    - Maintain active goal
    - Publish ready jobs to job board
    - Track job completion and update dependencies
    - Handle job failures
    """

    def __init__(self, world: World, name: str = "orchestrator", inbox_size: int = 50):
        super().__init__(name=name, inbox_size=inbox_size)
        self.world = world

        # Planners for different goal types
        self.craft_planner = CraftGoalPlanner(world)
        self.combat_planner = CombatGoalPlanner(world)
        self.skill_planner = SkillLevelGoalPlanner(world)

        # Current goal (MVP: single goal at a time)
        self.active_plan: Optional[Goal] = None

        # Job lookup
        self.jobs: Dict[str, Job] = {}

        self.logger = logging.getLogger("botman.orchestrator")

    async def on_start(self):
        self.logger.info("JobOrchestrator started")

    async def on_stop(self):
        self.logger.info("JobOrchestrator stopped")

    @singledispatchmethod
    async def on_receive(self, message) -> Any:
        """
        Handle typed messages from bots and UI using singledispatch.

        All messages must be dataclass instances for type safety.
        """
        self.logger.warning(f"Unknown message type: {type(message)}")
        return None

    @on_receive.register
    async def _(self, msg: QueryJobsRequest) -> QueryJobsResponse:
        """Handle job query request."""
        ready_jobs = []
        if self.active_plan:
            for job in self.active_plan.get_ready_jobs():
                if job.matches_bot(msg.role, msg.skills):
                    ready_jobs.append(job)
        return QueryJobsResponse(jobs=ready_jobs)

    @on_receive.register
    async def _(self, msg: ClaimJobRequest) -> ClaimJobResponse:
        """Handle job claim request."""
        job = self.jobs.get(msg.job_id)
        if not job:
            return ClaimJobResponse(success=False, error=f"Job {msg.job_id} not found")

        if job.status != JobStatus.PENDING:
            return ClaimJobResponse(
                success=False,
                error=f"Job {msg.job_id} is not pending (status: {job.status})",
            )

        job.status = JobStatus.CLAIMED
        job.claimed_by = msg.bot_name
        self.logger.info(f"Job {msg.job_id} claimed by {msg.bot_name}")
        return ClaimJobResponse(success=True)

    @on_receive.register
    async def _(self, msg: CompleteJobRequest) -> CompleteJobResponse:
        """Handle job completion request."""
        job = self.jobs.get(msg.job_id)
        if not job:
            return CompleteJobResponse(
                success=False, error=f"Job {msg.job_id} not found"
            )

        job.status = JobStatus.COMPLETED
        if self.active_plan:
            self.active_plan.mark_completed(msg.job_id)

        self.logger.info(
            f"Job {msg.job_id} completed by {msg.bot_name} - "
            f"Plan progress: {self.active_plan.progress_summary() if self.active_plan else 'N/A'}"
        )

        plan_complete = self.active_plan.is_complete() if self.active_plan else False
        if plan_complete and self.active_plan:
            self.logger.info(f"Plan {self.active_plan.plan_id} completed!")
            self.active_plan = None
            self.jobs = {}

        return CompleteJobResponse(success=True, plan_complete=plan_complete)

    @on_receive.register
    async def _(self, msg: FailJobRequest) -> FailJobResponse:
        """Handle job failure request."""
        job = self.jobs.get(msg.job_id)
        if not job:
            return FailJobResponse(success=False, error=f"Job {msg.job_id} not found")

        job.status = JobStatus.PENDING
        job.claimed_by = None
        self.logger.warning(
            f"Job {msg.job_id} failed by {msg.bot_name}: {msg.error} - reset to pending"
        )
        return FailJobResponse(success=True, status="reset_to_pending")

    @on_receive.register
    async def _(self, msg: GetPlanStatusRequest) -> GetPlanStatusResponse:
        """Handle plan status request."""
        if not self.active_plan:
            return GetPlanStatusResponse(active=False)

        jobs_by_status: Dict[str, List[Dict[str, Any]]] = {
            "pending": [],
            "claimed": [],
            "in_progress": [],
            "completed": [],
            "failed": [],
        }

        for job in self.active_plan.all_jobs:
            jobs_by_status[job.status.value].append(self._serialize_job(job))

        return GetPlanStatusResponse(
            active=True,
            plan_id=self.active_plan.plan_id,
            goal_item=self.active_plan.description,
            goal_quantity=0,  # Not all goals have quantity
            progress=self.active_plan.progress_summary(),
            is_complete=self.active_plan.is_complete(),
            total_jobs=len(self.active_plan.all_jobs),
            jobs_by_status=jobs_by_status,
        )

    @on_receive.register
    async def _(self, msg: CreatePlanRequest) -> CreatePlanResponse:
        """Handle craft goal creation request."""
        if self.active_plan and not self.active_plan.is_complete():
            return CreatePlanResponse(
                success=False,
                error=f"Plan {self.active_plan.plan_id} is still active. Complete it first.",
            )

        self.logger.info(f"Creating craft goal for {msg.item_code} x{msg.quantity}")
        plan = self.craft_planner.create_plan(msg.item_code, msg.quantity)

        if not plan.all_jobs:
            return CreatePlanResponse(
                success=False,
                error=f"Could not create plan for {msg.item_code} - check if item is craftable",
            )

        self.active_plan = plan
        self.jobs = {job.id: job for job in plan.all_jobs}

        self.logger.info(
            f"Goal {plan.plan_id} created: {plan.description} ({len(plan.all_jobs)} jobs)"
        )

        return CreatePlanResponse(
            success=True,
            plan_id=plan.plan_id,
            total_jobs=len(plan.all_jobs),
            levels=len(plan.jobs_by_level),
        )

    @on_receive.register
    async def _(self, msg: CreateCombatGoalRequest) -> CreatePlanResponse:
        """Handle combat goal creation request."""
        if self.active_plan and not self.active_plan.is_complete():
            return CreatePlanResponse(
                success=False,
                error=f"Plan {self.active_plan.plan_id} is still active. Complete it first.",
            )

        self.logger.info(
            f"Creating combat goal: fight {msg.monster_code} for {msg.item_code} x{msg.quantity}"
        )
        plan = self.combat_planner.create_plan(msg.monster_code, msg.item_code, msg.quantity)

        if not plan.all_jobs:
            return CreatePlanResponse(
                success=False,
                error=f"Could not create plan to fight {msg.monster_code} for {msg.item_code}",
            )

        self.active_plan = plan
        self.jobs = {job.id: job for job in plan.all_jobs}

        self.logger.info(
            f"Goal {plan.plan_id} created: {plan.description} ({len(plan.all_jobs)} jobs)"
        )

        return CreatePlanResponse(
            success=True,
            plan_id=plan.plan_id,
            total_jobs=len(plan.all_jobs),
            levels=len(plan.jobs_by_level),
        )

    @on_receive.register
    async def _(self, msg: CreateSkillGoalRequest) -> CreatePlanResponse:
        """Handle skill leveling goal creation request."""
        if self.active_plan and not self.active_plan.is_complete():
            return CreatePlanResponse(
                success=False,
                error=f"Plan {self.active_plan.plan_id} is still active. Complete it first.",
            )

        self.logger.info(
            f"Creating skill goal for {msg.skill.value} to level {msg.target_level}"
        )
        plan = self.skill_planner.create_plan(
            msg.skill, msg.target_level, msg.current_level
        )

        if not plan.all_jobs:
            return CreatePlanResponse(
                success=False,
                error=f"Could not create plan for {msg.skill.value}",
            )

        self.active_plan = plan
        self.jobs = {job.id: job for job in plan.all_jobs}

        self.logger.info(
            f"Goal {plan.plan_id} created: {plan.description} ({len(plan.all_jobs)} jobs)"
        )

        return CreatePlanResponse(
            success=True,
            plan_id=plan.plan_id,
            total_jobs=len(plan.all_jobs),
            levels=len(plan.jobs_by_level),
        )

    @on_receive.register
    async def _(self, msg: ListCraftableItemsRequest) -> ListCraftableItemsResponse:
        """Handle list craftable items request."""
        items = self.craft_planner.list_craftable_items()
        return ListCraftableItemsResponse(
            items=[{"code": code, "name": name} for code, name in items]
        )

    def _serialize_job(self, job: Job) -> Dict[str, Any]:
        """Convert a Job to a dictionary for transmission."""
        from botman.core.mrp.registry import serialize_job

        return serialize_job(job)
