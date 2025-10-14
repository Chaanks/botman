import logging
import uuid
from collections import deque
from typing import Dict, Tuple, List, Optional
from abc import ABC, abstractmethod

from botman.core.mrp.models import (
    Job,
    JobType,
    JobStatus,
    Goal,
    GatherJob,
    CraftJob,
    FightJob,
)
from botman.core.api.models import Skill, Position, CharacterRole
from botman.core.world import World

logger = logging.getLogger(__name__)


class GoalPlanner(ABC):
    """Base class for goal planners."""

    def __init__(self, world: World):
        self.world = world

    @abstractmethod
    def create_plan(self, **kwargs) -> Goal:
        """Create a goal plan from parameters."""
        pass


class CraftGoalPlanner(GoalPlanner):
    """Plans crafting goals by performing BFS traversal of crafting trees."""

    def create_plan(self, item_code: str, quantity: int) -> Goal:
        """
        Create a production plan for crafting the specified item.

        Uses BFS to traverse the crafting tree and calculate all required materials.
        Organizes jobs by dependency level (higher level = must complete first).
        """
        plan_id = str(uuid.uuid4())[:8]
        plan = Goal(
            plan_id=plan_id,
            description=f"Craft {item_code} x{quantity}",
        )

        # BFS to calculate materials needed at each level
        materials_by_level = self._calculate_materials_bfs(item_code, quantity)

        if not materials_by_level:
            logger.error(
                f"Could not create plan for {item_code} - item not found or not craftable"
            )
            return plan

        # Convert materials to jobs, starting from highest level (raw materials)
        job_id_map: Dict[
            Tuple[str, int], List[str]
        ] = {}  # (item_code, level) -> job_ids

        for level in sorted(materials_by_level.keys(), reverse=True):
            materials = materials_by_level[level]
            logger.debug(f"Level {level}: {materials}")

            for material_code, needed_qty in materials.items():
                jobs = self._create_jobs_for_material(
                    material_code=material_code,
                    quantity=needed_qty,
                    level=level,
                    job_id_map=job_id_map,
                )

                if jobs:
                    # Store all job IDs for this material (for dependencies)
                    for job in jobs:
                        plan.add_job(job, level)
                        logger.debug(f"Created job: {job}")

                    # Map material to ALL job IDs (dependencies need to wait for all fragments)
                    job_id_map[(material_code, level)] = [job.id for job in jobs]
                else:
                    logger.warning(
                        f"Failed to create jobs for {material_code} x{needed_qty} at level {level}"
                    )

        logger.info(
            f"Created plan {plan_id}: {len(plan.all_jobs)} jobs across {len(plan.jobs_by_level)} levels"
        )
        return plan

    def _calculate_materials_bfs(
        self, item_code: str, quantity: int
    ) -> Dict[int, Dict[str, int]]:
        """
        BFS traversal to calculate all materials needed at each dependency level.

        Returns: Dict mapping level -> {material_code: quantity}
                 Level 0 = final item
                 Higher levels = dependencies (raw materials at highest level)
        """
        target_item = self.world.item(item_code)
        if not target_item:
            logger.error(f"Item {item_code} not found in world data")
            return {}

        if not target_item.craft:
            logger.error(f"Item {item_code} is not craftable")
            return {}

        # Track materials needed at each level
        materials_by_level: Dict[int, Dict[str, int]] = {0: {item_code: quantity}}

        # Queue: (item_code, quantity_needed, level)
        queue: deque[Tuple[str, int, int]] = deque([(item_code, quantity, 0)])
        processed: set[str] = set()

        while queue:
            current_code, current_qty, current_level = queue.popleft()

            # Avoid reprocessing
            if current_code in processed:
                continue
            processed.add(current_code)

            current_item = self.world.item(current_code)
            if not current_item:
                continue

            # Stop if not craftable (no recipe)
            if not current_item.craft:
                continue

            # Note: Some items are both type="resource" AND craftable (e.g., copper_bar)
            # We continue processing them since they have craft recipes

            # Calculate next level for dependencies
            next_level = current_level + 1
            if next_level not in materials_by_level:
                materials_by_level[next_level] = {}

            # Process each requirement
            for requirement in current_item.craft.requirements:
                req_code = requirement.code
                req_qty_per_craft = requirement.quantity

                # Calculate total quantity needed
                # Account for recipe output quantity (e.g., 1 recipe might produce 5 items)
                recipe_output = current_item.craft.quantity
                crafts_needed = (
                    current_qty + recipe_output - 1
                ) // recipe_output  # Ceiling division
                total_req_qty = req_qty_per_craft * crafts_needed

                # Add to materials needed at this level
                materials_by_level[next_level][req_code] = (
                    materials_by_level[next_level].get(req_code, 0) + total_req_qty
                )

                # Queue for further processing
                # (Will stop at resources or non-craftable items)
                queue.append((req_code, total_req_qty, next_level))

        return materials_by_level

    def _create_jobs_for_material(
        self,
        material_code: str,
        quantity: int,
        level: int,
        job_id_map: Dict[Tuple[str, int], List[str]],
    ) -> List[Job]:
        """
        Create job(s) (GATHER or CRAFT) for obtaining a material.

        May return multiple jobs for gathering (fragmented for parallelism).

        Args:
            material_code: The item to obtain
            quantity: How much is needed
            level: Dependency level (used to find dependencies)
            job_id_map: Map of (item_code, level) -> job_id(s) for tracking dependencies
        """
        item = self.world.item(material_code)
        if not item:
            logger.warning(f"Item {material_code} not found in world data")
            return []

        # Determine if this is a raw material or craftable item
        # Priority: If it has a craft recipe, it's craftable (even if type="resource")
        # Some items like bars are both type="resource" AND craftable
        if item.craft:
            # Craftable item - has a recipe (returns single job)
            job = self._create_craft_job(
                material_code, quantity, level, item, job_id_map
            )
            return [job] if job else []
        elif item.type == "resource":
            # Raw material that must be gathered/fought for
            if item.subtype == "mob":
                # Monster drop - create fight jobs
                return self._create_fight_jobs(material_code, quantity, level)
            else:
                # Gathering resource (may return multiple jobs for parallelism)
                return self._create_gather_jobs(material_code, quantity, level)
        else:
            logger.warning(f"Item {material_code} is neither a resource nor craftable")
            return []

    def _create_gather_job(
        self, item_code: str, quantity: int, level: int
    ) -> Optional[Job]:
        """
        Create GATHER job(s) for a raw material.

        For large quantities, creates multiple jobs to enable parallel gathering.
        Returns the first job (caller should use _create_gather_jobs for multiple).
        """
        # This method now just creates a single job
        # For fragmentation, use _create_gather_jobs instead
        return self._create_single_gather_job(item_code, quantity, level)

    def _create_single_gather_job(
        self, item_code: str, quantity: int, level: int, job_suffix: str = ""
    ) -> Optional[GatherJob]:
        """Create a single GATHER job for a raw material."""
        # Find the resource that drops this item
        resource = self.world.resource_from_drop(item_code)
        if not resource:
            logger.warning(f"No resource found that drops {item_code}")
            return None

        # Determine skill from resource
        skill = Skill(resource.skill) if resource.skill else None

        # Find gathering location (location of the resource, not the item)
        location = self.world.gathering_location(resource.code)
        position = Position(x=location[0], y=location[1]) if location else None

        job_id = f"gather_{item_code}_{uuid.uuid4().hex[:6]}{job_suffix}"

        return GatherJob(
            id=job_id,
            type=JobType.GATHER,
            required_role=CharacterRole.GATHERER,
            item_code=item_code,  # The item we want to gather
            quantity=quantity,
            required_skill=skill,
            location=position,
            depends_on=set(),  # Raw materials have no dependencies
            status=JobStatus.PENDING,
        )

    def _create_gather_jobs(
        self, item_code: str, quantity: int, level: int
    ) -> List[Job]:
        """
        Create one or more GATHER jobs with fragmentation for parallelism.

        Static policy: Split into batches of 20 items each.
        """
        BATCH_SIZE = 20

        # Calculate number of jobs needed
        num_jobs = (quantity + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division

        # Split quantity across jobs
        base_qty = quantity // num_jobs
        remainder = quantity % num_jobs

        jobs = []
        for i in range(num_jobs):
            # Distribute remainder across first few jobs
            job_qty = base_qty + (1 if i < remainder else 0)

            suffix = f"_part{i + 1}" if num_jobs > 1 else ""
            job = self._create_single_gather_job(item_code, job_qty, level, suffix)

            if job:
                jobs.append(job)
                logger.debug(
                    f"Created gather job {i + 1}/{num_jobs}: {item_code} x{job_qty}"
                )

        return jobs

    def _create_fight_jobs(
        self, item_code: str, quantity: int, level: int
    ) -> List[Job]:
        """
        Create one or more FIGHT jobs with fragmentation for parallelism.

        Static policy: Split into batches of 10 drops each.
        Combat is slower than gathering, so use smaller batch sizes.
        """
        BATCH_SIZE = 10

        # Find monster that drops this item
        monster = None
        for m in self.world.monsters.values():
            if m.drops:
                for drop in m.drops:
                    if drop.code == item_code:
                        monster = m
                        break
            if monster:
                break

        if not monster:
            logger.warning(f"No monster found that drops {item_code}")
            return []

        # Calculate number of jobs needed
        # Note: Location lookup is handled by FightTask itself
        num_jobs = (quantity + BATCH_SIZE - 1) // BATCH_SIZE  # Ceiling division

        # Split quantity across jobs
        base_qty = quantity // num_jobs
        remainder = quantity % num_jobs

        jobs = []
        for i in range(num_jobs):
            # Distribute remainder across first few jobs
            job_qty = base_qty + (1 if i < remainder else 0)

            suffix = f"_part{i + 1}" if num_jobs > 1 else ""
            job_id = f"fight_{monster.code}_{item_code}_{uuid.uuid4().hex[:6]}{suffix}"

            fight_job = FightJob(
                id=job_id,
                type=JobType.FIGHT,
                required_role=CharacterRole.FIGHTER,
                monster_code=monster.code,
                item_code=item_code,
                quantity=job_qty,
                location=None,  # FightTask handles location lookup
                depends_on=set(),  # Mob drops have no dependencies (raw materials)
                status=JobStatus.PENDING,
            )

            jobs.append(fight_job)
            logger.debug(
                f"Created fight job {i + 1}/{num_jobs}: {monster.code} for {item_code} x{job_qty}"
            )

        return jobs

    def _create_craft_job(
        self,
        item_code: str,
        quantity: int,
        level: int,
        item,
        job_id_map: Dict[Tuple[str, int], List[str]],
    ) -> Optional[CraftJob]:
        """Create a CRAFT job for a craftable item."""
        if not item.craft:
            return None

        # Determine skill from craft info
        skill = Skill(item.craft.skill) if item.craft.skill else None

        # Determine role based on skill type
        # Gathering skills (mining, woodcutting, fishing) → GATHERER role
        # These are typically resource processing (ore→bar, wood→plank, fish→cooked fish)
        # Crafting skills (weaponcrafting, gearcrafting, etc.) → CRAFTER role
        gathering_skills = {Skill.MINING, Skill.WOODCUTTING, Skill.FISHING}

        if skill and skill in gathering_skills:
            role = CharacterRole.GATHERER
        else:
            role = CharacterRole.CRAFTER

        # Find dependencies (requirements at the next level)
        depends_on: set[str] = set()
        next_level = level + 1

        for requirement in item.craft.requirements:
            req_code = requirement.code
            # Look up job IDs for this requirement (always a list, may contain 1 or more jobs)
            dep_job_ids = job_id_map.get((req_code, next_level))
            if dep_job_ids:
                depends_on.update(dep_job_ids)

        job_id = f"craft_{item_code}_{uuid.uuid4().hex[:6]}"

        return CraftJob(
            id=job_id,
            type=JobType.CRAFT,
            required_role=role,
            required_skill=skill,
            item_code=item_code,
            quantity=quantity,
            location=None,  # Crafting location determined by workshop type
            depends_on=depends_on,
            status=JobStatus.PENDING,
        )

    def list_craftable_items(self) -> List[Tuple[str, str]]:
        """
        Get a list of all craftable items in the world.

        Returns: List of (item_code, item_name) tuples
        """
        craftable = []
        for item in self.world.items.values():
            if item.craft:
                craftable.append((item.code, item.name))
        craftable.sort(key=lambda x: x[1])  # Sort by name
        return craftable


class CombatGoalPlanner(GoalPlanner):
    """Plans combat goals (fight monsters for specific drops)."""

    def create_plan(self, monster_code: str, item_code: str, quantity: int) -> Goal:
        """Create a goal to fight monsters for specific drop items."""
        plan_id = str(uuid.uuid4())[:8]
        plan = Goal(
            plan_id=plan_id,
            description=f"Fight {monster_code} for {item_code} x{quantity}",
        )

        # Verify monster exists
        monster = self.world.monster(monster_code)
        if not monster:
            logger.error(f"Monster {monster_code} not found in world data")
            return plan

        # Create a single fight job (no fragmentation for standalone combat goals)
        job_id = f"fight_{monster_code}_{item_code}_{uuid.uuid4().hex[:6]}"

        fight_job = FightJob(
            id=job_id,
            type=JobType.FIGHT,
            required_role=CharacterRole.FIGHTER,
            monster_code=monster_code,
            item_code=item_code,
            quantity=quantity,
            location=None,  # FightTask handles location lookup
            depends_on=set(),
            status=JobStatus.PENDING,
        )

        plan.add_job(fight_job, level=0)
        logger.info(f"Created combat plan {plan_id}: fight {monster_code} for {item_code} x{quantity}")
        return plan


class SkillLevelGoalPlanner(GoalPlanner):
    """Plans skill leveling goals (reach skill level N)."""

    def create_plan(self, skill: Skill, target_level: int, current_level: int = 0) -> Goal:
        """
        Create a goal to reach a target skill level.

        Strategy: Find the highest-level resource/item that gives XP for this skill
        and create gather/craft jobs for it.
        """
        plan_id = str(uuid.uuid4())[:8]
        plan = Goal(
            plan_id=plan_id,
            description=f"Level {skill.value} to {target_level}",
        )

        # For gathering skills: find highest gathering resource
        if skill in {Skill.MINING, Skill.WOODCUTTING, Skill.FISHING}:
            resource = self.world.highest_gathering_resource(skill, target_level)
            if not resource:
                logger.error(f"No resource found for skill {skill.value}")
                return plan

            # Estimate: roughly 20 items per level (simplified)
            levels_needed = target_level - current_level
            quantity = levels_needed * 20

            job_id = f"gather_{resource.code}_{uuid.uuid4().hex[:6]}"
            location = self.world.gathering_location(resource.code)
            position = Position(x=location[0], y=location[1]) if location else None

            gather_job = GatherJob(
                id=job_id,
                type=JobType.GATHER,
                required_role=CharacterRole.GATHERER,
                item_code=resource.drop.code if resource.drop else resource.code,
                quantity=quantity,
                required_skill=skill,
                location=position,
                depends_on=set(),
                status=JobStatus.PENDING,
            )

            plan.add_job(gather_job, level=0)

        # For crafting skills: find highest craftable item
        elif skill in {Skill.WEAPONCRAFTING, Skill.GEARCRAFTING, Skill.JEWELRYCRAFTING, Skill.COOKING}:
            # Find highest level craftable item for this skill
            best_item = None
            best_level = 0

            for item in self.world.items.values():
                if item.craft and item.craft.skill == skill.value:
                    if item.craft.level > best_level:
                        best_level = item.craft.level
                        best_item = item

            if not best_item:
                logger.error(f"No craftable item found for skill {skill.value}")
                return plan

            # Estimate: roughly 10 crafts per level (simplified)
            levels_needed = target_level - current_level
            quantity = levels_needed * 10

            # Use CraftGoalPlanner to handle dependencies
            craft_planner = CraftGoalPlanner(self.world)
            craft_plan = craft_planner.create_plan(best_item.code, quantity)

            # Copy jobs from craft plan
            for level, jobs in enumerate(craft_plan.jobs_by_level):
                for job in jobs:
                    plan.add_job(job, level)

        logger.info(f"Created skill plan {plan_id}: {skill.value} to level {target_level}")
        return plan
