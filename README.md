# Artifacts MMO Bot

<!-- Small centered logo -->
<p align="center">
  <img src="./assets/logo.jpg" alt="Bot Logo" width="180"/>
</p>


## Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                    TEXTUAL TUI (asyncio)                        │
│  Dashboard | Task Queue | Bank Status | Logs | Command Input    │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    Subscribes/Publishes
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                   PUBSUB BROKER (Thread-safe)                   │
│  Topics: orchestrator.command | bot.*.message | ui.*            │
└──┬──────────────────────────────────────┬───────────────────────┘
   │                                      │
   │                                      │
┌──▼────────────┐                    ┌───▼─────────┐
│ Orchestrator  │                    │  BankActor  │
│    Actor      │                    │             │
└───────────────┘                    └─────────────┘
       │
       │ Assigns tasks
       │
┌──────▼───────────────────────────────────────────────────┐
│                     BOT ACTORS                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Bot_0   │  │  Bot_1   │  │  Bot_2   │  │  Bot_N   │  │
│  └─────┬────┘  └─────┬────┘  └─────┬────┘  └─────┬────┘  │
└────────┼─────────────┼─────────────┼─────────────┼───────┘
         │             │             │             │
         └─────────────┴─────────────┴─────────────┘
                                 │
                                 │ Each bot has own API connection
                                 │
                    ┌────────────▼─────────────┐
                    │    GAME API (MMO Server) │
                    └──────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│            SHARED READ-ONLY DATA (Class-level)                  │
│  GameDataCache | World (Maps, Monsters, Items) | Database       │
└─────────────────────────────────────────────────────────────────┘
```