"""Main entry point for bot manager"""

import asyncio
import os
import argparse
import time
import threading
import logging
from queue import Empty

from broker import PubSub
from bot import Bot
from api import ArtifactsClient
from world import World
from tui import BotManagerUI


def setup_logging(log_file="botman.log"):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, mode="a"),
            # Optionally also log to console in no-TUI mode
            # logging.StreamHandler()
        ],
    )
    return logging.getLogger("botman")


async def initialize_bots(token: str, character_names: list):
    """Initialize bots with real characters from API"""
    logger = logging.getLogger("botman")
    pubsub = PubSub()
    bot_actors = []

    # Create a temporary API client for world initialization
    print("Initializing world data...")
    logger.info("Initializing world data...")
    async with ArtifactsClient(token) as init_api:
        world = await World.create(init_api)
    logger.info(
        f"Loaded world: {len(world.items)} items, {len(world.resources)} resources, "
        f"{len(world.maps)} maps, {len(world.monsters)} monsters"
    )

    logger.info("Initializing bots...")

    for name in character_names:
        try:
            bot = Bot.start(name, token, pubsub, world)
            bot_actors.append(bot)
            logger.info(f"Starting bot: {name}")

        except Exception as e:
            import traceback

            logger.error(f"Failed to start bot {name}:\n{traceback.format_exc()}")

    return pubsub, bot_actors, character_names


def main():
    TOKEN = os.getenv("ARTIFACTS_TOKEN")
    if not TOKEN:
        print("Error: ARTIFACTS_TOKEN environment variable not set")
        return

    CHARACTER_NAMES = ["AAA", "BBB", "CCC", "DDD", "EEE"]

    pubsub, bot_actors, bot_names = asyncio.run(initialize_bots(TOKEN, CHARACTER_NAMES))

    from tui import BotManagerUI

    app = BotManagerUI(pubsub, bot_names)

    try:
        app.run()
    finally:
        print("\nStopping bots...")
        for bot in bot_actors:
            bot.stop()
        print("Shutdown complete")


if __name__ == "__main__":
    main()
