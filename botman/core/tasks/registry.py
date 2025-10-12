"""
Task registry and factory for creating tasks from web UI input.
"""
from typing import Dict, Any, Optional, Type, List
from dataclasses import fields

from botman.core.tasks.base import Task
from botman.core.tasks.gather import GatherTask
from botman.core.tasks.fight import FightTask
from botman.core.tasks.deposit import DepositTask
from botman.core.tasks.craft import CraftTask
from botman.core.tasks.withdraw import WithdrawTask

TASK_REGISTRY: Dict[str, Type[Task]] = {
    "gather": GatherTask,
    "fight": FightTask,
    "deposit": DepositTask,
    "craft": CraftTask,
    "withdraw": WithdrawTask,
}


class TaskFactory:
    """Factory for creating task instances from web form data."""

    @staticmethod
    def create_task(task_type: str, params: Dict[str, Any]) -> Optional[Task]:
        task_class = TASK_REGISTRY.get(task_type)
        if not task_class:
            return None

        # Parse parameters based on task class fields
        parsed_params = TaskFactory._parse_params(task_class, params)

        try:
            return task_class(**parsed_params)
        except Exception as e:
            raise ValueError(f"Failed to create {task_type} task: {str(e)}")

    @staticmethod
    def _parse_params(task_class: Type[Task], params: Dict[str, Any]) -> Dict[str, Any]:
        parsed = {}
        task_fields = {f.name: f for f in fields(task_class)}

        for key, value in params.items():
            if key not in task_fields:
                continue

            field = task_fields[key]
            field_type = field.type

            # Handle Optional types
            if hasattr(field_type, '__origin__') and field_type.__origin__ is type(Optional):
                # Get the actual type from Optional[T]
                inner_type = field_type.__args__[0]
                field_type = inner_type

            # Convert value to appropriate type
            if value == "" or value is None:
                parsed[key] = None
            elif field_type == int:
                parsed[key] = int(value)
            elif field_type == float:
                parsed[key] = float(value)
            elif field_type == bool:
                parsed[key] = value if isinstance(value, bool) else value.lower() in ('true', '1', 'yes')
            else:
                parsed[key] = value

        return parsed

    @staticmethod
    def get_task_schema(task_type: str) -> Optional[Dict[str, Any]]:
        task_class = TASK_REGISTRY.get(task_type)
        if not task_class:
            return None

        schema = {
            "task_type": task_type,
            "fields": []
        }

        for field in fields(task_class):
            # Skip internal/progress tracking fields
            if field.name in ('crafted_amount', 'gathered_amount', 'items'):
                continue

            field_info = {
                "name": field.name,
                "type": str(field.type),
                "required": field.default == field.default_factory if hasattr(field, 'default_factory') else field.default is field.default,
            }

            # Add default value if available
            if field.default is not field.default_factory if hasattr(field, 'default_factory') else True:
                field_info["default"] = field.default

            schema["fields"].append(field_info)

        return schema

    @staticmethod
    def list_task_types() -> List[str]:
        return list(TASK_REGISTRY.keys())
