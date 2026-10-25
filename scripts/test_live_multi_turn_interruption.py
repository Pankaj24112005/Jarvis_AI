import asyncio
import os
import sys
import time
from google import genai
from google.genai import types

sys.path.insert(0, ".")
from jarvis.config import Settings

async def main():
    settings = Settings()
    api_key = settings.gemini_api_key.get_secret_value()
    client = genai.Client(api_key=api_key)

    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Charon")
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part.from_text(text="You are JARVIS. Answer concisely in one short sentence.")]
        ),
    )

    print("Connecting to Gemini Live session...", flush=True)
    async with client.aio.live.connect(
        model="models/gemini-3.1-flash-live-preview",
        config=live_config,
    ) as session:
        print("Connected!", flush=True)

        receive_queue = asyncio.Queue()
        stop_event = asyncio.Event()

        # PERSISTENT receive loop across multiple turns!
        async def receive_loop():
            try:
                while not stop_event.is_set():
                    async for msg in session.receive():
                        await receive_queue.put(msg)
                        if stop_event.is_set():
                            break
            except asyncio.CancelledError:
                print("receive_loop cancelled cleanly", flush=True)
            except Exception as e:
                print(f"receive_loop error: {e}", flush=True)

        recv_task = asyncio.create_task(receive_loop())

        async def do_turn(turn_num: int, prompt: str, interrupt_after_chunks: int | None = None):
            print(f"\n--- Turn {turn_num}: Sending '{prompt}' ---", flush=True)
            # Use send_client_content for text prompts in Live API
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                turn_complete=True,
            )
            print(f"Turn {turn_num}: Sent prompt with turn_complete=True", flush=True)

            chunk_count = 0
            interrupted = False
            while True:
                try:
                    msg = await asyncio.wait_for(receive_queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    print(f"Turn {turn_num}: Timeout waiting for server response!", flush=True)
                    break

                if msg.server_content:
                    if getattr(msg.server_content, "interrupted", False):
                        print(f"Turn {turn_num}: Server signaled interrupted=True", flush=True)
                        interrupted = True

                    if msg.server_content.model_turn:
                        for p in msg.server_content.model_turn.parts:
                            if p.inline_data and p.inline_data.data:
                                chunk_count += 1
                                if interrupt_after_chunks and chunk_count >= interrupt_after_chunks:
                                    print(f"Turn {turn_num}: [SIMULATING USER INTERRUPTION] after {chunk_count} chunks!", flush=True)
                                    return True

                    if getattr(msg.server_content, "turn_complete", False):
                        print(f"Turn {turn_num}: Complete! Received {chunk_count} audio chunks.", flush=True)
                        break

            return True

        # Turn 1: Normal turn
        await do_turn(1, "Hello JARVIS, count from 1 to 3.")
        await asyncio.sleep(0.5)

        # Turn 2: Normal turn
        await do_turn(2, "What is the capital of France?")
        await asyncio.sleep(0.5)

        # Turn 3: User interrupts after 2 chunks!
        await do_turn(3, "Tell me a long story about space exploration.", interrupt_after_chunks=2)
        print("Interruption occurred. User immediately starts Turn 4!", flush=True)

        # Turn 4: User speaks again right after interruption!
        await do_turn(4, "Stop that. Just tell me what 2 plus 2 is.")
        await asyncio.sleep(0.5)

        # Turn 5: Normal turn
        await do_turn(5, "Are you still functioning perfectly, JARVIS?")

        print("\nAll 5 turns completed on the SAME persistent session without reconnecting!", flush=True)
        stop_event.set()
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    asyncio.run(main())
