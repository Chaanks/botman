from dataclasses import dataclass

from botman.core.tasks.base import Task, TaskContext, TaskResult
from botman.core.errors import APIError, FatalError, RecoverableError, RetriableError


@dataclass
class FightTask(Task):
    monster_code: str
    target_kills: int
    kills: int = 0

    async def execute(self, context: TaskContext) -> TaskResult:
        name = context.character.name
        monster = context.world.monster(self.monster_code)

        if not monster:
            error = FatalError(
                code=1000,
                message=f"Monster '{self.monster_code}' not found in world data."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        # Find monster location
        location = context.world.gathering_location(self.monster_code)
        if not location:
            error = FatalError(
                code=1000,
                message=f"Monster '{self.monster_code}' location not found."
            )
            return TaskResult(
                completed=False,
                character=context.character,
                error=error,
                log_messages=[(str(error), "ERROR")],
            )

        target_x, target_y = location
        current_pos = context.character.position

        # Step 1: Move to the monster
        if (current_pos.x, current_pos.y) != (target_x, target_y):
            try:
                result = await context.api.move(x=target_x, y=target_y, name=name)
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[(f"Moving to {monster.name} at ({target_x}, {target_y})", "INFO")],
                )
            except APIError as e:
                return TaskResult(completed=False, character=context.character, error=e)

        # Step 2: Check HP and rest if needed
        hp = context.character.stats.hp
        max_hp = context.character.stats.max_hp

        if hp < max_hp:
            try:
                result = await context.api.rest(name)
                return TaskResult(
                    completed=False,
                    character=result.character,
                    log_messages=[(f"Resting to recover HP ({hp}/{max_hp})", "INFO")],
                )
            except APIError as e:
                return TaskResult(completed=False, character=context.character, error=e)

        # Step 3: Fight the monster
        try:
            result = await context.api.fight(name=name)
            self.kills += 1

            fight_result = result.fight.result  # "win" or "lose"

            # Get character-specific fight results (for solo, there's only one)
            char_result = result.fight.characters[0] if result.fight.characters else None
            xp_gained = char_result.xp if char_result else 0
            gold_gained = char_result.gold if char_result else 0
            items_dropped = [f"{drop.code} x{drop.quantity}" for drop in char_result.drops] if char_result else []
            items_str = ", ".join(items_dropped) if items_dropped else "nothing"

            # Get updated character state
            character = result.characters[0] if result.characters else context.character

            completed = self.kills >= self.target_kills

            log_messages = [
                (f"Fight {fight_result}! XP: +{xp_gained}, Gold: +{gold_gained}, Drops: {items_str} ({self.kills}/{self.target_kills})", "INFO")
            ]

            if completed:
                log_messages.append((f"Fighting complete for {monster.name}!", "INFO"))

            return TaskResult(
                completed=completed,
                character=character,
                log_messages=log_messages,
            )
        except APIError as e:
            level = "WARNING" if isinstance(e, (RecoverableError, RetriableError)) else "ERROR"
            return TaskResult(
                completed=False,
                character=context.character,
                error=e,
                log_messages=[(f"Fight failed: {e.message}", level)]
            )

    def progress(self) -> str:
        return f"{self.kills}/{self.target_kills}"

    def description(self) -> str:
        monster = self.monster_code.replace("_", " ").title()
        return f"Fight {monster} x{self.target_kills}"
