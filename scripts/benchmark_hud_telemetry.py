"""Benchmark telemetry throughput, CPU consumption, and memory footprint of JARVIS Visualizer."""

import asyncio
import os
import time
import psutil
import websockets

from jarvis.core.state import AgentState, StateMachine
from jarvis.events import EventBus, EventType
from jarvis.visualizer.adapter import VisualizerAdapter
from jarvis.visualizer.server import VisualizerServer


async def main():
    proc = psutil.Process(os.getpid())
    mem_before_mb = proc.memory_info().rss / (1024 * 1024)

    bus = EventBus()
    sm = StateMachine(event_bus=bus)
    adapter = VisualizerAdapter(event_bus=bus, state_machine=sm, voice_name="Charon")
    server = VisualizerServer(adapter=adapter, host="127.0.0.1", port=8995)

    url = await server.start()
    ws_url = f"ws://127.0.0.1:{server.actual_port}/ws/telemetry"

    # Measure idle resource baseline
    await asyncio.sleep(0.5)
    idle_cpu = proc.cpu_percent(interval=0.5)

    # Connect WebSocket client and receive stream
    received_frames = []

    async def client_receiver(ws):
        try:
            while True:
                msg = await ws.recv()
                received_frames.append(msg)
        except Exception:
            pass

    async with websockets.connect(ws_url) as ws:
        receiver_task = asyncio.create_task(client_receiver(ws))

        # Reset CPU counter
        proc.cpu_percent(interval=None)
        t_start = time.time()
        turns = 3

        for _ in range(turns):
            # 1. User holds PTT (LISTENING)
            await sm.transition_to(AgentState.LISTENING)
            for _ in range(15):
                await bus.emit(EventType.VOICE_AUDIO_CHUNK, {"size": 1024})
                await asyncio.sleep(0.033)

            # 2. Release PTT (THINKING)
            await sm.transition_to(AgentState.THINKING)
            await asyncio.sleep(0.15)

            # 3. Model speaks (SPEAKING)
            await sm.transition_to(AgentState.SPEAKING)
            for _ in range(15):
                await bus.emit(EventType.VOICE_AUDIO_CHUNK, {"size": 2048})
                await asyncio.sleep(0.033)

            # 4. Return to IDLE
            await sm.transition_to(AgentState.IDLE)
            await asyncio.sleep(0.1)

        t_elapsed = time.time() - t_start
        await asyncio.sleep(0.2)
        receiver_task.cancel()

        active_cpu = proc.cpu_percent(interval=None)
        mem_active_mb = proc.memory_info().rss / (1024 * 1024)

    await server.stop()

    effective_msg_rate = len(received_frames) / t_elapsed

    print("=== JARVIS VISUALIZER PERFORMANCE MEASUREMENTS ===")
    print(f"Server URL: {url}")
    print(f"Frames Received by Client: {len(received_frames)} in {t_elapsed:.2f}s")
    print(f"Measured WebSocket Message Rate: {effective_msg_rate:.1f} msgs/sec")
    print(f"Python Idle CPU: {idle_cpu:.2f}%")
    print(f"Python Active Streaming CPU: {active_cpu:.2f}%")
    print(f"Python Baseline Memory: {mem_before_mb:.1f} MB")
    print(f"Python Active Memory: {mem_active_mb:.1f} MB (Delta: +{mem_active_mb - mem_before_mb:.2f} MB)")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(main())
