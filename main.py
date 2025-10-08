"""Main entry point for bot manager"""

import asyncio
import os
import argparse
import time
import threading
from queue import Empty

from broker import PubSub
from bot import Bot
from api import ArtifactsClient
from world import World


class ConsoleLogger:
    """Simple console logger for no-TUI mode"""

    def __init__(self, pubsub: PubSub):
        self.pubsub = pubsub
        self.running = True

        # Subscribe to logs
        self.log_queue = pubsub.subscribe("ui.log")
        self.update_queue = pubsub.subscribe("ui.bot_update")

        # Start log processor
        self.thread = threading.Thread(target=self._process_logs)
        self.thread.daemon = True
        self.thread.start()

    def _process_logs(self):
        """Process and print logs to console"""
        while self.running:
            try:
                # Process logs
                try:
                    message = self.log_queue.get_nowait()
                    data = message.data
                    timestamp = time.strftime("%H:%M:%S")
                    print(
                        f"[{timestamp}] [{data['level']}] {data['source']}: {data['message']}"
                    )
                except Empty:
                    pass

                # Process bot updates (print status changes)
                try:
                    message = self.update_queue.get_nowait()
                    data = message.data.get("data")
                    if data:
                        timestamp = time.strftime("%H:%M:%S")
                        print(
                            f"[{timestamp}] [STATUS] {data.bot_name}: {data.status} | "
                            f"Task: {data.current_task or 'None'} ({data.progress})"
                        )
                except Empty:
                    pass

            except Exception as e:
                print(f"Error processing logs: {e}")

            time.sleep(0.1)

    def stop(self):
        self.running = False


async def initialize_bots(token: str, character_names: list):
    """Initialize bots with real characters from API"""
    api = ArtifactsClient(token)
    pubsub = PubSub()
    bot_actors = []

    print("Initializing world data...")
    world = await World.create(api)
    print(
        f"✓ Loaded world: {len(world.items)} items, {len(world.resources)} resources, "
        f"{len(world.maps)} maps, {len(world.monsters)} monsters"
    )

    print("Initializing bots...")

    for name in character_names:
        try:
            character = await api.get_character(name)
            print(f"✓ Loaded character: {character.name} (Lvl {character.level})")

            bot = Bot.start(name, pubsub, character, api, world)
            bot_actors.append(bot)

        except Exception as e:
            print(f"✗ Failed to load {name}: {e}")

    return pubsub, bot_actors, [name for name in character_names]


def main():
    parser = argparse.ArgumentParser(description="Artifacts MMO Bot Manager")
    parser.add_argument(
        "--no-tui", action="store_true", help="Run without TUI (console mode)"
    )
    args = parser.parse_args()

    TOKEN = os.getenv("ARTIFACTS_TOKEN")
    if not TOKEN:
        print("Error: ARTIFACTS_TOKEN environment variable not set")
        return

    CHARACTER_NAMES = ["AAA", "BBB", "CCC", "DDD", "EEE"]

    pubsub, bot_actors, bot_names = asyncio.run(initialize_bots(TOKEN, CHARACTER_NAMES))

    if not bot_actors:
        print("Error: No bots initialized")
        return

    print(f"\nStarted {len(bot_actors)} bots")

    if args.no_tui:
        # Console mode
        print("Running in console mode (no TUI). Press Ctrl+C to quit.\n")

        logger = ConsoleLogger(pubsub)

        try:
            # Keep running until interrupted
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n\nShutting down...")
        finally:
            logger.stop()
            for bot in bot_actors:
                bot.stop()
            print("Shutdown complete")

    else:
        # TUI mode
        print("Starting UI...")
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
