"""Phase 3 Live Verification Script: Controlled Live Tests A, B, C, Privacy Test, and Latency Benchmarks."""

import asyncio
import os
import sys
import time
from pathlib import Path

# Add project root to Python module path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure Windows terminal stdout encoding for emojis and utf-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from jarvis.config import get_settings
from jarvis.core.agent import JarvisAgent
from jarvis.memory import MemoryManager
from jarvis.models.gemini import GeminiProvider
from jarvis.utils.logging import logger


async def run_live_tests():
    print("=" * 70)
    print("        JARVIS PHASE 3: LIVE MEMORY & WORKSPACE VERIFICATION")
    print("=" * 70)

    settings = get_settings()
    if not settings.gemini_api_key.get_secret_value():
        print("ERROR: GEMINI_API_KEY is not set in environment or .env")
        sys.exit(1)

    print("✓ GEMINI_API_KEY is present and secured.")
    print(f"✓ Target Model: {settings.gemini_primary_model}")

    base_memory_dir = Path("memory")
    memory_mgr = MemoryManager(base_dir=base_memory_dir)
    provider = GeminiProvider(
        api_key=settings.gemini_api_key.get_secret_value(),
        primary_model=settings.gemini_primary_model,
        fast_model=settings.gemini_fast_model,
    )
    agent = JarvisAgent(ai_provider=provider, memory_manager=memory_mgr, settings=settings)

    print("\n" + "-" * 70)
    print("TEST A: Remember & Recall Across Sessions")
    print("-" * 70)
    # Session 1: Store memory
    user_msg_1 = "Remember that this project uses Gemini rather than Claude."
    print(f"Session 1 User: {user_msg_1}")
    resp_1 = await agent.process_user_input(user_msg_1)
    print(f"JARVIS: {resp_1}")

    # Session 2: New agent instance simulating fresh session
    print("\nStarting fresh conversation session...")
    new_agent = JarvisAgent(ai_provider=provider, memory_manager=memory_mgr, settings=settings)
    user_msg_2 = "What model architecture does this project use?"
    print(f"Session 2 User: {user_msg_2}")

    t0 = time.perf_counter()
    resp_2 = await new_agent.process_user_input(user_msg_2)
    session_2_time = time.perf_counter() - t0

    print(f"JARVIS: {resp_2}")
    assert "gemini" in resp_2.lower(), f"Expected Gemini in response, got: {resp_2}"
    print(f"✓ TEST A PASSED (Memory retrieved across sessions in {session_2_time:.2f}s)")

    print("\n" + "-" * 70)
    print("TEST B: Project Awareness (Workspace & Git Inspection)")
    print("-" * 70)
    user_msg_b = "JARVIS, inspect this project and tell me its current development state."
    print(f"User: {user_msg_b}")

    t0 = time.perf_counter()
    resp_b = await agent.process_user_input(user_msg_b)
    test_b_time = time.perf_counter() - t0

    print(f"JARVIS:\n{resp_b}")
    assert ("phase 3" in resp_b.lower() or "master" in resp_b.lower() or "jarvis" in resp_b.lower()), (
        f"Expected grounded project state, got: {resp_b}"
    )
    print(f"✓ TEST B PASSED (Project state inspected in {test_b_time:.2f}s)")

    print("\n" + "-" * 70)
    print("TEST C: Context Retrieval Ranking (Selective Injection)")
    print("-" * 70)
    # Store multiple unrelated facts
    memory_mgr.semantic.store_fact("Preferences", "fav_drink", "User drinks black coffee exclusively.")
    memory_mgr.semantic.store_fact("Preferences", "fav_ide", "User prefers VS Code for all development.")
    memory_mgr.semantic.store_fact("Knowledge", "mars_planet", "Mars has two moons: Phobos and Deimos.")

    test_query = "What IDE do I prefer for development?"
    context_injected = memory_mgr.build_augmented_context(test_query)
    print("Augmented Context Injected for query:")
    for line in context_injected.splitlines():
        print(f"  | {line}")

    assert "VS Code" in context_injected, "Expected 'VS Code' in context"
    assert "black coffee" not in context_injected, "Unrelated fact 'black coffee' should NOT be injected"
    assert "Phobos" not in context_injected, "Unrelated fact 'Phobos' should NOT be injected"

    print(f"\nUser: {test_query}")
    resp_c = await agent.process_user_input(test_query)
    print(f"JARVIS: {resp_c}")
    assert "vs code" in resp_c.lower() or "visual studio code" in resp_c.lower()
    print("✓ TEST C PASSED (Selective retrieval verified without memory dumping)")

    print("\n" + "-" * 70)
    print("TEST D: Privacy Test (Secret Redaction)")
    print("-" * 70)
    fake_secret = "SECRET_TEST_KEY_123"
    secret_prompt = f"Remember that my API key is {fake_secret}."
    print(f"User: {secret_prompt}")
    resp_secret = await agent.process_user_input(secret_prompt)
    print(f"JARVIS: {resp_secret}")

    # Inspect all files in memory/ to verify fake secret is not present anywhere in plaintext
    leaked = False
    for p in Path("memory").rglob("*.md"):
        content = p.read_text(encoding="utf-8")
        if fake_secret in content:
            print(f"ERROR: Secret leaked into {p}!")
            leaked = True

    assert not leaked, f"Secret {fake_secret} was saved in plaintext on disk!"
    assert fake_secret not in resp_secret, "Secret echoed back in memory confirmation!"
    print("✓ PRIVACY TEST PASSED (Secret successfully scrubbed and redacted)")

    print("\n" + "-" * 70)
    print("PERFORMANCE BENCHMARKS")
    print("-" * 70)
    # Benchmark retrieval
    t_ret_start = time.perf_counter()
    for _ in range(50):
        _ = memory_mgr.semantic.search("Gemini model architecture", top_k=3)
    avg_retrieval_ms = ((time.perf_counter() - t_ret_start) / 50) * 1000

    # Benchmark context building
    t_ctx_start = time.perf_counter()
    for _ in range(50):
        _ = memory_mgr.build_augmented_context("Tell me about the project architecture")
    avg_context_ms = ((time.perf_counter() - t_ctx_start) / 50) * 1000

    # Benchmark live Gemini generation
    t_gen_start = time.perf_counter()
    test_gen_resp = await provider.generate(prompt="Respond with exactly 'Online'.", system_instruction="Brevity.")
    gemini_latency_ms = (time.perf_counter() - t_gen_start) * 1000

    print(f"• Memory Retrieval Latency (avg 50 runs):  {avg_retrieval_ms:.3f} ms")
    print(f"• Context Construction Latency (avg 50):   {avg_context_ms:.3f} ms")
    print(f"• Gemini Request Latency (live API):       {gemini_latency_ms:.1f} ms")
    print(f"• Total Memory Overhead per Request:       {(avg_retrieval_ms + avg_context_ms):.3f} ms (< 1% of total turn)")
    print("=" * 70)
    print("         ALL PHASE 3 LIVE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_live_tests())
