"""Job Orchestrator - manages production plans and coordinates job execution."""

import logging
from typing import Dict, Any, Optional, List
from functools import singledispatchmethod

from botman.core.actor import Actor
from botman.core.mrp.models import Job, JobStatus, ProductionPlan
from botman.core.mrp.planner import MaterialRequirementsPlanner
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
    ListCraftableItemsRequest,
    ListCraftableItemsResponse,
)
from botman.core.world import World
from botman.core.bot import BotRole
from botman.core.models import Skill

logger = logging.getLogger(__name__)


class JobOrchestrator(Actor):
    """
    Central coordinator for production plans and job execution.

    Responsibilities:
    - Create production plans from goals
    - Maintain active production plan
    - Publish ready jobs to job board
    - Track job completion and update dependencies
    - Handle job failures
    """

    def __init__(self, world: World):
        super().__init__()
        self.world = world
        self.planner = MaterialRequirementsPlanner(world)

        # Current production plan (MVP: single plan at a time)
        self.active_plan: Optional[ProductionPlan] = None

        # Job lookup
        self.jobs: Dict[str, Job] = {}

        self.logger = logging.getLogger("botman.orchestrator")

    async def on_start(self):
        self.logger.info("JobOrchestrator started")

    async def on_stop(self):
        self.logger.info("JobOrchestrator stopped")

    async def on_receive(self, message: Any) -> Optional[Any]:
        """
        Handle messages from bots and UI.

        Supports both:
        - Typed message objects (preferred) - returns typed response object
        - Dict-based messages (legacy) - returns dict
        """
        # Typed message path - return typed response object directly!
        if not isinstance(message, dict):
            return await self.handle(message)

        # Legacy dict-based routing (for backwards compatibility)
        msg_type = message.get("type")
        if msg_type == "create_plan":
            return await self._handle_create_plan(message)
        elif msg_type == "query_jobs":
            return await self._handle_query_jobs(message)
        elif msg_type == "claim_job":
            return await self._handle_claim_job(message)
        elif msg_type == "complete_job":
            return await self._handle_complete_job(message)
        elif msg_type == "fail_job":
            return await self._handle_fail_job(message)
        elif msg_type == "get_plan_status":
            return await self._handle_get_plan_status(message)
        elif msg_type == "list_craftable_items":
            return await self._handle_list_craftable_items(message)
        else:
            self.logger.warning(f"Unknown message type: {msg_type}")
            return None

    @singledispatchmethod
    async def handle(self, message) -> Any:
        """Type-safe message handler using single dispatch."""
        self.logger.warning(f"Unknown message type: {type(message)}")
        return None

    @handle.register
    async def _(self, msg: QueryJobsRequest) -> QueryJobsResponse:
        """Handle job query request."""
        ready_jobs = []
        if self.active_plan:
            for job in self.active_plan.get_ready_jobs():
                if job.matches_bot(msg.role, msg.skills):
                    ready_jobs.append(job)
        return QueryJobsResponse(jobs=ready_jobs)

    @handle.register
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

    @handle.register
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

    @handle.register
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

    @handle.register
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
            goal_item=self.active_plan.goal_item,
            goal_quantity=self.active_plan.goal_quantity,
            progress=self.active_plan.progress_summary(),
            is_complete=self.active_plan.is_complete(),
            total_jobs=len(self.active_plan.all_jobs),
            jobs_by_status=jobs_by_status,
        )

    @handle.register
    async def _(self, msg: CreatePlanRequest) -> CreatePlanResponse:
        """Handle plan creation request."""
        if self.active_plan and not self.active_plan.is_complete():
            return CreatePlanResponse(
                success=False,
                error=f"Plan {self.active_plan.plan_id} is still active. Complete it first.",
            )

        self.logger.info(
            f"Creating production plan for {msg.item_code} x{msg.quantity}"
        )
        plan = self.planner.create_plan(msg.item_code, msg.quantity)

        if not plan.all_jobs:
            return CreatePlanResponse(
                success=False,
                error=f"Could not create plan for {msg.item_code} - check if item is craftable",
            )

        self.active_plan = plan
        self.jobs = {job.id: job for job in plan.all_jobs}

        self.logger.info(
            f"Plan {plan.plan_id} created with {len(plan.all_jobs)} jobs across {len(plan.jobs_by_level)} levels"
        )

        return CreatePlanResponse(
            success=True,
            plan_id=plan.plan_id,
            total_jobs=len(plan.all_jobs),
            levels=len(plan.jobs_by_level),
        )

    @handle.register
    async def _(self, msg: ListCraftableItemsRequest) -> ListCraftableItemsResponse:
        """Handle list craftable items request."""
        items = self.planner.list_craftable_items()
        return ListCraftableItemsResponse(
            items=[{"code": code, "name": name} for code, name in items]
        )

    # Legacy dict-based handlers (for backwards compatibility)

    async def _handle_create_plan(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new production plan."""
        item_code = message.get("item_code")
        quantity = message.get("quantity", 1)

        if not item_code:
            return {"success": False, "error": "item_code is required"}

        # For MVP, only one plan at a time
        if self.active_plan and not self.active_plan.is_complete():
            return {
                "success": False,
                "error": f"Plan {self.active_plan.plan_id} is still active. Complete it first.",
            }

        # Create the plan
        self.logger.info(f"Creating production plan for {item_code} x{quantity}")
        plan = self.planner.create_plan(item_code, quantity)

        if not plan.all_jobs:
            return {
                "success": False,
                "error": f"Could not create plan for {item_code} - check if item is craftable",
            }

        # Store the plan
        self.active_plan = plan
        self.jobs = {job.id: job for job in plan.all_jobs}

        self.logger.info(
            f"Plan {plan.plan_id} created with {len(plan.all_jobs)} jobs across {len(plan.jobs_by_level)} levels"
        )

        return {
            "success": True,
            "plan_id": plan.plan_id,
            "total_jobs": len(plan.all_jobs),
            "levels": len(plan.jobs_by_level),
        }

    async def _handle_query_jobs(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Return jobs that match the bot's role and skills."""
        role_str = message.get("role")
        skills_str = message.get("skills", [])

        if not role_str:
            return {"jobs": []}

        role = BotRole(role_str)
        skills = [Skill(s) for s in skills_str]

        # Find ready jobs that match this bot
        ready_jobs = []

        if self.active_plan:
            for job in self.active_plan.get_ready_jobs():
                if job.matches_bot(role, skills):
                    ready_jobs.append(self._serialize_job(job))

        return {"jobs": ready_jobs}

    async def _handle_claim_job(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Mark a job as claimed by a bot."""
        job_id = message.get("job_id")
        bot_name = message.get("bot_name")

        if not job_id or not bot_name:
            return {"success": False, "error": "job_id and bot_name required"}

        job = self.jobs.get(job_id)
        if not job:
            return {"success": False, "error": f"Job {job_id} not found"}

        if job.status != JobStatus.PENDING:
            return {
                "success": False,
                "error": f"Job {job_id} is not pending (status: {job.status})",
            }

        # Claim the job
        job.status = JobStatus.CLAIMED
        job.claimed_by = bot_name

        self.logger.info(f"Job {job_id} claimed by {bot_name}")

        return {"success": True}

    async def _handle_complete_job(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Mark a job as completed and publish dependent jobs."""
        job_id = message.get("job_id")
        bot_name = message.get("bot_name")

        if not job_id:
            return {"success": False, "error": "job_id required"}

        job = self.jobs.get(job_id)
        if not job:
            return {"success": False, "error": f"Job {job_id} not found"}

        # Update job status
        job.status = JobStatus.COMPLETED

        # Mark as completed in the plan
        if self.active_plan:
            self.active_plan.mark_completed(job_id)

        self.logger.info(
            f"Job {job_id} completed by {bot_name} - "
            f"Plan progress: {self.active_plan.progress_summary() if self.active_plan else 'N/A'}"
        )

        # Check if plan is complete
        plan_complete = self.active_plan.is_complete() if self.active_plan else False

        # Clear active plan when complete
        if plan_complete and self.active_plan:
            self.logger.info(f"Plan {self.active_plan.plan_id} completed!")
            self.active_plan = None
            self.jobs = {}

        return {"success": True, "plan_complete": plan_complete}

    async def _handle_fail_job(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a failed job - reset to pending for retry."""
        job_id = message.get("job_id")
        bot_name = message.get("bot_name")
        error = message.get("error", "Unknown error")

        if not job_id:
            return {"success": False, "error": "job_id required"}

        job = self.jobs.get(job_id)
        if not job:
            return {"success": False, "error": f"Job {job_id} not found"}

        # Reset job to pending so another bot can try
        job.status = JobStatus.PENDING
        job.claimed_by = None

        self.logger.warning(
            f"Job {job_id} failed by {bot_name}: {error} - reset to pending"
        )

        return {"success": True, "status": "reset_to_pending"}

    async def _handle_get_plan_status(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Get the status of the active production plan."""
        if not self.active_plan:
            return {"active": False}

        # Organize jobs by status
        jobs_by_status: Dict[str, List[Dict[str, Any]]] = {
            "pending": [],
            "claimed": [],
            "in_progress": [],
            "completed": [],
            "failed": [],
        }

        for job in self.active_plan.all_jobs:
            jobs_by_status[job.status.value].append(self._serialize_job(job))

        return {
            "active": True,
            "plan_id": self.active_plan.plan_id,
            "goal_item": self.active_plan.goal_item,
            "goal_quantity": self.active_plan.goal_quantity,
            "progress": self.active_plan.progress_summary(),
            "is_complete": self.active_plan.is_complete(),
            "total_jobs": len(self.active_plan.all_jobs),
            "jobs_by_status": jobs_by_status,
        }

    async def _handle_list_craftable_items(
        self, message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get list of all craftable items."""
        items = self.planner.list_craftable_items()
        return {"items": [{"code": code, "name": name} for code, name in items]}

    def _serialize_job(self, job: Job) -> Dict[str, Any]:
        """Convert a Job to a dictionary for transmission."""
        from botman.core.mrp.registry import serialize_job

        return serialize_job(job)
