from api import ArtifactsClient

TOKEN = "è_é"

async def main():
    print("Hello World!")
    api = ArtifactsClient(TOKEN)
    character = await api.get_character("AAA")
    print(character)
    print(character.cooldown_info)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
