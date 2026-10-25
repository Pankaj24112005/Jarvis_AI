import sys
sys.path.insert(0, ".")
import asyncio
import inspect
from google import genai
from google.genai import types
from jarvis.config import Settings

async def main():
    settings = Settings()
    api_key = settings.gemini_api_key.get_secret_value()
    client = genai.Client(api_key=api_key)
    cfg = types.LiveConnectConfig(response_modalities=["AUDIO"])

    async with client.aio.live.connect(model="models/gemini-3.1-flash-live-preview", config=cfg) as session:
        for method_name in ["send_realtime_input", "send_client_content", "send", "close", "receive", "start_stream"]:
            method = getattr(session, method_name)
            sig = inspect.signature(method)
            doc = inspect.getdoc(method) or "No doc"
            print(f"\n--- {method_name}{sig} ---")
            print(doc[:300])

if __name__ == "__main__":
    asyncio.run(main())
