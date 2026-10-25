import asyncio
import sys
sys.path.insert(0, ".")
from google import genai
from google.genai import types
from jarvis.config import Settings

async def probe():
    settings = Settings()
    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
            )
        )
    )
    async with client.aio.live.connect(model="models/gemini-3.1-flash-live-preview", config=cfg) as session:
        print("Connected!")
        # Send a tiny PCM chunk
        await session.send_realtime_input(audio=types.Blob(data=b"\x00\x00"*800, mime_type="audio/pcm;rate=16000"))
        print("Sent audio")
        await session.send_realtime_input(audio_stream_end=True)
        print("Sent audio_stream_end=True")
        count = 0
        async for msg in session.receive():
            count += 1
            tc = getattr(msg.server_content, "turn_complete", None) if msg.server_content else None
            print(f"Msg {count}: tc={tc}")
            if tc:
                print("Turn 1 complete!")
                break
        print("After loop 1!")

        # Now try turn 2!
        try:
            print("Sending audio for turn 2...")
            await session.send_realtime_input(audio=types.Blob(data=b"\x00\x00"*800, mime_type="audio/pcm;rate=16000"))
            print("Sent audio turn 2!")
            await session.send_realtime_input(audio_stream_end=True)
            print("Sent audio_stream_end turn 2!")
            count2 = 0
            async for msg in session.receive():
                count2 += 1
                tc2 = getattr(msg.server_content, "turn_complete", None) if msg.server_content else None
                print(f"Turn 2 Msg {count2}: tc={tc2}")
                if tc2:
                    break
            print("Turn 2 finished successfully!")
        except Exception as e:
            print("Turn 2 failed:", e)

if __name__ == "__main__":
    asyncio.run(probe())
