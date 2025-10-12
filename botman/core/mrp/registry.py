from typing import Dict, Any, Type
from botman.core.mrp.models import Job, JobType, JobStatus, GatherJob, CraftJob
from botman.core.api.models import Position, Skill, CharacterRole


# Registry mapping JobType to Job class
_JOB_REGISTRY: Dict[JobType, Type[Job]] = {
    JobType.GATHER: GatherJob,
    JobType.CRAFT: CraftJob,
}


def deserialize_job(job_dict: Dict[str, Any]) -> Job:
    """
    Reconstruct a Job object from a serialized dictionary.

    Uses the job registry to instantiate the correct Job subclass.
    """
    # Parse common fields
    job_id = job_dict["id"]
    job_type = JobType(job_dict["type"])
    required_role = CharacterRole(job_dict["required_role"])
    item_code = job_dict["item_code"]
    quantity = job_dict["quantity"]
    required_skill = (
        Skill(job_dict["required_skill"]) if job_dict.get("required_skill") else None
    )
    location_data = job_dict.get("location")
    location = (
        Position(x=location_data["x"], y=location_data["y"]) if location_data else None
    )
    depends_on = set(job_dict.get("depends_on", []))
    status = JobStatus(job_dict["status"])
    claimed_by = job_dict.get("claimed_by")

    # Look up the job class from registry
    job_class = _JOB_REGISTRY.get(job_type)
    if not job_class:
        raise ValueError(f"Unknown job type: {job_type}")

    # Instantiate the concrete job class
    return job_class(
        id=job_id,
        type=job_type,
        required_role=required_role,
        item_code=item_code,
        quantity=quantity,
        required_skill=required_skill,
        location=location,
        depends_on=depends_on,
        status=status,
        claimed_by=claimed_by,
    )


def serialize_job(job: Job) -> Dict[str, Any]:
    """
    Convert a Job to a dictionary for transmission.

    Works with any Job subclass via polymorphism.
    """
    return {
        "id": job.id,
        "type": job.type.value,
        "required_role": job.required_role.value,
        "required_skill": job.required_skill.value if job.required_skill else None,
        "item_code": job.item_code,
        "quantity": job.quantity,
        "location": {"x": job.location.x, "y": job.location.y}
        if job.location
        else None,
        "depends_on": list(job.depends_on),
        "status": job.status.value,
        "claimed_by": job.claimed_by,
    }
