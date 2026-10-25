import asyncio
import io
import os
import sys
import time
from google import genai
from google.genai import types

sys.path.insert(0, ".")
from jarvis.config import Settings
from jarvis.voice.audio_io import PygameAudioOutput, calculate_pcm_duration
import pygame

async def test_voice(voice_name: str):
    print(f"\n==========================================", flush=True)
    print(f"Testing Voice: {voice_name}", flush=True)
    print(f"==========================================", flush=True)

    settings = Settings()
    api_key = settings.gemini_api_key.get_secret_value()
    client = genai.Client(api_key=api_key)

    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text="You are JARVIS. Speak concisely in one short sentence.")]
        ),
    )

    chunks = []
    total_bytes = 0
    t0 = time.time()
    try:
        async with client.aio.live.connect(
            model="models/gemini-3.1-flash-live-preview",
            config=live_config,
        ) as session:
            print(f"Connected to Live API with voice: {voice_name} in {time.time() - t0:.2f}s", flush=True)

            # Send a prompt
            await session.send_realtime_input(text="Hello JARVIS, state your name and role briefly.")
            await session.send_realtime_input(audio_stream_end=True)

            async for msg in session.receive():
                if msg.server_content:
                    if msg.server_content.model_turn:
                        for part in msg.server_content.model_turn.parts:
                            if part.inline_data and part.inline_data.data:
                                data = part.inline_data.data
                                chunks.append(data)
                                total_bytes += len(data)
                                samples = len(data) // 2
                                dur = samples / 24000
                                print(f"  Chunk {len(chunks)}: {len(data)} bytes, {samples} samples, expected dur: {dur:.3f}s", flush=True)
                            if part.text:
                                print(f"  Text part: {part.text}", flush=True)

                    if getattr(msg.server_content, "turn_complete", False):
                        print(f"Turn complete received for {voice_name}.", flush=True)
                        break

        total_samples = total_bytes // 2
        total_duration = total_samples / 24000
        print(f"Summary for {voice_name}:", flush=True)
        print(f"  Total chunks: {len(chunks)}", flush=True)
        print(f"  Total bytes: {total_bytes}", flush=True)
        print(f"  Total samples: {total_samples}", flush=True)
        print(f"  Total calculated duration (@ 24000 Hz, 16-bit mono): {total_duration:.3f}s", flush=True)
        return True, total_duration, chunks
    except Exception as ex:
        print(f"ERROR testing voice {voice_name}: {ex}", flush=True)
        return False, 0.0, []

async def main():
    voices = ["Charon", "Orus", "Gacrux"]
    results = {}
    for v in voices:
        success, dur, chunks = await test_voice(v)
        results[v] = {"success": success, "duration": dur, "chunk_count": len(chunks)}
    print("\nALL VOICE RESULTS:", results, flush=True)

if __name__ == "__main__":
    asyncio.run(main())
