from typing import Optional
from collections import deque

from api import ArtifactsClient
from models import Item, Map, Monster, Resource, Skill


class World:
    """Game world data"""

    def __init__(self):
        self.items: dict[str, Item] = {}
        self.maps: dict[str, Map] = {}
        self.monsters: dict[str, Monster] = {}
        self.resources: dict[str, Resource] = {}

    @classmethod
    async def create(cls, api: ArtifactsClient) -> "World":
        """Create and initialize world from API"""
        world = cls()
        await world.initialize(api)
        return world

    async def initialize(self, api: ArtifactsClient) -> None:
        """Fetch all game data from API"""
        items = await self._fetch_all_pages(api.get_items)
        monsters = await self._fetch_all_pages(api.get_monsters)
        resources = await self._fetch_all_pages(api.get_resources)

        self.items = {item.code: item for item in items}
        self.monsters = {monster.code: monster for monster in monsters}
        self.resources = {resource.code: resource for resource in resources}

        # Fetch all maps and filter for those with content
        all_maps = await self._fetch_all_pages(api.get_maps)

        self.maps = {}
        for map_obj in all_maps:
            if map_obj.content is not None:
                self.maps[map_obj.content.code] = map_obj

    async def _fetch_all_pages(self, fetch_func, page_size: int = 50):
        """Fetch all pages from a paginated endpoint"""
        all_items = []
        page = 1

        while True:
            result = await fetch_func(page=page, size=page_size)
            all_items.extend(result.data)

            if page >= result.pages:
                break

            page += 1

        return all_items

    def resource(self, code: str) -> Optional[Resource]:
        return self.resources.get(code)

    def resource_from_drop(self, item_code: str) -> Optional[Resource]:
        for resource in self.resources.values():
            if any(drop.code == item_code for drop in resource.drops):
                return resource
        return None

    def item(self, code: str) -> Optional[Item]:
        return self.items.get(code)

    def monster(self, code: str) -> Optional[Monster]:
        return self.monsters.get(code)

    def map_by_content(self, content_code: str) -> Optional[Map]:
        return self.maps.get(content_code)

    def map_by_skill(self, skill: Skill) -> Optional[Map]:
        return self.map_by_content(skill.value)

    def gathering_location(self, resource_code: str) -> Optional[tuple[int, int]]:
        map_obj = self.map_by_content(resource_code)
        if map_obj:
            return (map_obj.x, map_obj.y)
        return None

    def available_gathering_resources(
        self, skill: Skill, level: int
    ) -> list[Resource]:
        resources = [
            res
            for res in self.resources.values()
            if res.skill == skill.value and res.level <= level
        ]
        resources.sort(key=lambda r: r.level, reverse=True)
        return resources

    def highest_gathering_resource(self, skill: Skill, level: int) -> Optional[Resource]:
        available = self.available_gathering_resources(skill, level)
        return available[0] if available else None

    def recipe_graph(self, item_code: str) -> list[Item]:
        graph: list[Item] = []
        queue = deque[str]()

        target_item = self.item(item_code)
        if not target_item:
            return graph

        graph.append(target_item)

        if target_item.craft and "items" in target_item.craft:
            for mat in target_item.craft["items"]:
                queue.append(mat["code"])

        while queue:
            material_code = queue.popleft()
            material = self.item(material_code)

            if not material:
                continue

            if material.subtype in ("mining", "woodcutting"):
                continue

            graph.append(material)

            if material.craft and "items" in material.craft:
                for mat in material.craft["items"]:
                    queue.append(mat["code"])

        return graph


    def items_by_type(self, item_type: str) -> list[Item]:
        """Get all items of a specific type"""
        return [item for item in self.items.values() if item.type == item_type]

    def is_resource(self, code: str) -> bool:
        """Check if code is a resource node"""
        return code in self.resources

    def is_item(self, code: str) -> bool:
        """Check if code is an item"""
        return code in self.items

    def __repr__(self) -> str:
        return (
            f"<World: {len(self.items)} items, {len(self.maps)} maps, "
            f"{len(self.monsters)} monsters, {len(self.resources)} resources>"
        )
