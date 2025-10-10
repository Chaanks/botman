import pickle
from pathlib import Path
from typing import Optional

from api import ArtifactsClient
from models import Item, Map, Monster, Resource, Skill


class World:
    """Game world data"""

    CACHE_FILE = Path(".cache/world_data.pkl")

    def __init__(self):
        self.items: dict[str, Item] = {}
        self.maps: dict[str, Map] = {}
        self.monsters: dict[str, Monster] = {}
        self.resources: dict[str, Resource] = {}

    @classmethod
    async def create(cls, api: ArtifactsClient) -> "World":
        world = cls()

        if world._load_from_cache():
            print("✓ Loaded world data from cache")
            return world

        print("Fetching world data from API...")
        await world.initialize(api)
        world._save_to_cache()
        print("✓ World data fetched and cached")

        return world

    def _load_from_cache(self) -> bool:
        if not self.CACHE_FILE.exists():
            return False

        try:
            with open(self.CACHE_FILE, "rb") as f:
                cached_data = pickle.load(f)

            self.items = cached_data["items"]
            self.maps = cached_data["maps"]
            self.monsters = cached_data["monsters"]
            self.resources = cached_data["resources"]

            return True

        except Exception as e:
            print(f"Failed to load cache: {e}")
            return False

    def _save_to_cache(self) -> None:
        try:
            self.CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

            cache_data = {
                "items": self.items,
                "maps": self.maps,
                "monsters": self.monsters,
                "resources": self.resources,
            }

            with open(self.CACHE_FILE, "wb") as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

        except Exception as e:
            print(f"Failed to save cache: {e}")

    async def initialize(self, api: ArtifactsClient) -> None:
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

    async def _fetch_all_pages(self, fetch_func, page_size: int = 100):
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

    def available_gathering_resources(self, skill: Skill, level: int) -> list[Resource]:
        resources = [
            res
            for res in self.resources.values()
            if res.skill == skill.value and res.level <= level
        ]
        resources.sort(key=lambda r: r.level, reverse=True)
        return resources

    def highest_gathering_resource(
        self, skill: Skill, level: int
    ) -> Optional[Resource]:
        available = self.available_gathering_resources(skill, level)
        return available[0] if available else None

    def recipe_graph(self, item_code: str) -> list[Item]:
        from collections import deque

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
        return [item for item in self.items.values() if item.type == item_type]

    def is_resource(self, code: str) -> bool:
        return code in self.resources

    def is_item(self, code: str) -> bool:
        return code in self.items

    def __repr__(self) -> str:
        return (
            f"<World: {len(self.items)} items, {len(self.maps)} maps, "
            f"{len(self.monsters)} monsters, {len(self.resources)} resources>"
        )
