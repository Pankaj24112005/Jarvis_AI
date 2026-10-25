import sys
sys.path.insert(0, ".")
import asyncio
import inspect
from google import genai
from jarvis.config import Settings

async def main():
    settings = Settings()
    api_key = settings.gemini_api_key.get_secret_value()
    client = genai.Client(api_key=api_key)

    from google.genai import types
    cfg = types.LiveConnectConfig(response_modalities=["AUDIO"])
    async with client.aio.live.connect(model="models/gemini-3.1-flash-live-preview", config=cfg) as session:
        print("Session class:", type(session), flush=True)
        for name, member in inspect.getmembers(session):
            if not name.startswith("_"):
                print(f"session member: {name} -> {member}", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
