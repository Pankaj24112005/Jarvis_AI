"""Comprehensive automated test suite for Phase 3: Multi-Tier Memory and Workspace Awareness."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from jarvis.core.agent import JarvisAgent
from jarvis.memory.episodic import EpisodicMemory
from jarvis.memory.manager import MemoryManager
from jarvis.memory.project import ProjectMemory
from jarvis.memory.security import contains_secrets, redact_secrets
from jarvis.memory.semantic import KeywordRelevanceRetriever, MemoryFact, SemanticMemory
from jarvis.memory.short_term import MessageTurn, ShortTermMemory
from jarvis.memory.working import TaskState, WorkingMemory
from jarvis.models.base import AIProvider, ModelResponse


# ---------------------------------------------------------------------------
# 1. Short-Term Memory Tests
# ---------------------------------------------------------------------------
class TestShortTermMemory:
    def test_add_turns_and_retrieval(self):
        stm = ShortTermMemory(max_turns=5, max_tokens=1000)
        t1 = stm.add_turn("user", "Hello JARVIS")
        t2 = stm.add_turn("assistant", "Greetings, Sir.")

        assert len(stm.get_turns()) == 2
        assert stm.get_turns()[0].role == "user"
        assert stm.get_turns()[1].role == "assistant"
        assert t1.estimated_tokens > 0

    def test_turn_limit_truncation(self):
        stm = ShortTermMemory(max_turns=3, max_tokens=1000)
        stm.add_turn("user", "Turn 1")
        stm.add_turn("assistant", "Turn 2")
        stm.add_turn("user", "Turn 3")
        stm.add_turn("assistant", "Turn 4")

        turns = stm.get_turns()
        assert len(turns) == 3
        assert turns[0].content == "Turn 2"
        assert turns[-1].content == "Turn 4"

    def test_token_budget_truncation(self):
        # max 20 tokens (~80 chars)
        stm = ShortTermMemory(max_turns=10, max_tokens=20)
        stm.add_turn("user", "Short message")
        stm.add_turn("assistant", "A" * 60)  # ~15 tokens
        stm.add_turn("user", "B" * 60)  # ~15 tokens, should evict oldest

        assert stm.total_estimated_tokens <= 25
        assert len(stm.get_turns()) < 3

    def test_serialization(self):
        stm = ShortTermMemory()
        stm.add_turn("user", "Serialize me")
        stm.add_turn("assistant", "Serialized.")

        serialized = stm.to_list()
        assert len(serialized) == 2

        new_stm = ShortTermMemory()
        new_stm.from_list(serialized)
        assert len(new_stm.get_turns()) == 2
        assert new_stm.get_turns()[0].content == "Serialize me"

    def test_formatted_context(self):
        stm = ShortTermMemory()
        stm.add_turn("user", "Status report")
        stm.add_turn("assistant", "All systems nominal.")

        formatted = stm.get_formatted_context(assistant_name="JARVIS")
        assert "User: Status report" in formatted
        assert "JARVIS: All systems nominal." in formatted


# ---------------------------------------------------------------------------
# 2. Working Memory Tests
# ---------------------------------------------------------------------------
class TestWorkingMemory:
    def test_objective_and_steps(self):
        wm = WorkingMemory()
        assert not wm.is_active

        wm.set_objective("Refactor database layer", project="Backend", total_steps=4)
        assert wm.is_active
        assert wm.objective == "Refactor database layer"

        wm.set_step(2)
        summary = wm.get_summary()
        assert "Active Objective: Refactor database layer" in summary
        assert "Step: 2/4" in summary
        assert "Project: Backend" in summary

    def test_variables_and_tool_results(self):
        wm = WorkingMemory()
        wm.set_variable("target_table", "users")
        assert wm.get_variable("target_table") == "users"
        assert wm.get_variable("missing_key", "default_val") == "default_val"

        wm.record_tool_result("read_file", {"lines": 42})
        wm.record_decision("Opted for PostgreSQL dialect")
        wm.track_file_modified("db/schema.sql")

        assert "db/schema.sql" in wm._state.modified_files
        assert len(wm._state.decisions) == 1
        assert len(wm._state.tool_results) == 1

    def test_reset_lifecycle(self):
        wm = WorkingMemory()
        wm.set_objective("Deploy staging")
        wm.set_variable("env", "staging")
        wm.reset()

        assert not wm.is_active
        assert wm.objective == ""
        assert wm.get_variable("env") is None
        assert wm.get_summary() == ""


# ---------------------------------------------------------------------------
# 3. Episodic Memory Tests
# ---------------------------------------------------------------------------
class TestEpisodicMemory:
    def test_log_and_read_episode(self, tmp_path):
        ep_mem = EpisodicMemory(base_dir=tmp_path)
        entry = ep_mem.log_episode(
            user_request="Deploy phase 3 memory architecture",
            result_summary="Completed implementation of all 5 tiers",
            session_id="session_test_1",
            tools_used=["write_file", "git_status"],
            decisions=["Use local-first markdown vault"],
            force=True,
        )

        assert entry is not None
        assert "write_file" in entry.tools_used
        assert len(entry.decisions) == 1

        recent = ep_mem.get_recent_episodes(days=1)
        assert len(recent) >= 1
        assert "Deploy phase 3" in recent[0].user_request

    def test_significance_filter(self, tmp_path):
        ep_mem = EpisodicMemory(base_dir=tmp_path)

        # Casual greeting should not be persisted
        entry1 = ep_mem.log_episode(
            user_request="hello",
            result_summary="Hello Sir, how may I assist you?",
        )
        assert entry1 is None

        # Interaction with tool execution should be persisted
        entry2 = ep_mem.log_episode(
            user_request="list all workspace files",
            result_summary="Found 25 files in repository",
            tools_used=["list_dir"],
        )
        assert entry2 is not None

    def test_search_episodes(self, tmp_path):
        ep_mem = EpisodicMemory(base_dir=tmp_path)
        ep_mem.log_episode(
            user_request="Configure Docker container for deployment",
            result_summary="Built image v1.2",
            tools_used=["terminal_execute"],
            force=True,
        )
        ep_mem.log_episode(
            user_request="Write unit tests for authentication",
            result_summary="All 10 auth tests passed",
            tools_used=["terminal_execute"],
            force=True,
        )

        docker_matches = ep_mem.search_episodes("docker container")
        assert len(docker_matches) >= 1
        assert "Docker" in docker_matches[0].user_request


# ---------------------------------------------------------------------------
# 4. Semantic Memory Tests
# ---------------------------------------------------------------------------
class TestSemanticMemory:
    def test_store_and_retrieve_fact(self, tmp_path):
        sem = SemanticMemory(vault_dir=tmp_path)
        fact = sem.store_fact(
            category="Preferences",
            key="preferred_language",
            content="User prefers Python over JavaScript for backend systems.",
            tags=["python", "preferences"],
        )

        assert fact.key == "preferred_language"
        retrieved = sem.get_fact("Preferences", "preferred_language")
        assert retrieved is not None
        assert "Python" in retrieved.content

    def test_update_fact(self, tmp_path):
        sem = SemanticMemory(vault_dir=tmp_path)
        sem.store_fact("Preferences", "editor", "User prefers Sublime Text.")
        updated = sem.update_fact("Preferences", "editor", "User prefers VS Code.")

        assert updated is not None
        assert "VS Code" in updated.content

        fact = sem.get_fact("Preferences", "editor")
        assert fact is not None
        assert "VS Code" in fact.content

    def test_forget_fact(self, tmp_path):
        sem = SemanticMemory(vault_dir=tmp_path)
        sem.store_fact("Knowledge", "temp_fact", "Temporary fact to forget.")
        assert sem.get_fact("Knowledge", "temp_fact") is not None

        forgotten = sem.forget_fact("Knowledge", "temp_fact")
        assert forgotten is True
        assert sem.get_fact("Knowledge", "temp_fact") is None

    def test_relevance_ranking_search(self, tmp_path):
        sem = SemanticMemory(vault_dir=tmp_path)
        sem.store_fact("Preferences", "theme", "User prefers dark cybernetic themes.")
        sem.store_fact("Projects", "jarvis_model", "JARVIS uses Google Gemini rather than Claude.")
        sem.store_fact("Knowledge", "weather_info", "Paris has temperate oceanic climate.")

        results = sem.search(query="Which AI model does JARVIS use?", top_k=2)
        assert len(results) > 0
        assert results[0].key == "jarvis_model"
        assert "Gemini" in results[0].content


# ---------------------------------------------------------------------------
# 5. Project Memory Tests
# ---------------------------------------------------------------------------
class TestProjectMemory:
    def test_read_project_metadata(self, tmp_path):
        dot_jarvis = tmp_path / ".jarvis"
        dot_jarvis.mkdir()

        # Write mock project_state.json
        (dot_jarvis / "project_state.json").write_text(
            json.dumps({"name": "TestProject", "type": "CLI Tool", "active_phase": "Phase 3"}),
            encoding="utf-8",
        )
        # Write mock tasks.md
        (dot_jarvis / "tasks.md").write_text(
            "- [x] Phase 1\n- [x] Phase 2\n- [ ] Phase 3\n- [ ] Phase 4\n",
            encoding="utf-8",
        )
        # Write mock decisions.md
        (dot_jarvis / "decisions.md").write_text(
            "- Decision 1: Use Python 3.13\n- Decision 2: Local markdown storage\n",
            encoding="utf-8",
        )

        pm = ProjectMemory(workspace_path=tmp_path)
        assert pm.has_project_state()

        state = pm.get_project_state()
        assert state.project_name == "TestProject"
        assert state.active_phase == "Phase 3"
        assert len(state.completed_tasks) == 2
        assert len(state.pending_tasks) == 2
        assert len(state.recent_decisions) == 2

    def test_continuity_summary(self, tmp_path):
        dot_jarvis = tmp_path / ".jarvis"
        dot_jarvis.mkdir()
        (dot_jarvis / "project_state.json").write_text(
            json.dumps({"name": "ContinuityBot", "type": "Autonomous Agent", "active_phase": "Phase 3"}),
            encoding="utf-8",
        )
        (dot_jarvis / "tasks.md").write_text(
            "- [x] Setup repository\n- [ ] Implement memory layer\n",
            encoding="utf-8",
        )

        pm = ProjectMemory(workspace_path=tmp_path)
        summary = pm.get_continuity_summary()
        assert "ContinuityBot" in summary
        assert "Setup repository" in summary
        assert "Next Logical Task: Implement memory layer" in summary


# ---------------------------------------------------------------------------
# 6. Security and Secret Redaction Tests
# ---------------------------------------------------------------------------
class TestSecurityRedaction:
    def test_secret_detection(self):
        assert contains_secrets("My key is AIzaSyD9876543210zyxwvutsrqponmlkjihgfed")
        assert contains_secrets("sk-1234567890abcdefghijklmnopqrstuvwxyz")
        assert contains_secrets("Remember that my secret is SECRET_TEST_KEY_123")
        assert contains_secrets("Authorization: Bearer my_secret_token_1234567890")
        assert contains_secrets("password='SuperSecretPassword123'")
        assert not contains_secrets("JARVIS is an intelligent operating assistant.")

    def test_secret_redaction(self):
        text = "API Key: AIzaSyD9876543210zyxwvutsrqponmlkjihgfed and SECRET_TEST_KEY_123"
        sanitized = redact_secrets(text)
        assert "AIzaSyD9876543210zyxwvutsrqponmlkjihgfed" not in sanitized
        assert "SECRET_TEST_KEY_123" not in sanitized
        assert "[REDACTED_GEMINI_KEY]" in sanitized or "[REDACTED_SECRET]" in sanitized

    def test_redaction_before_persistent_storage(self, tmp_path):
        sem = SemanticMemory(vault_dir=tmp_path)
        fact = sem.store_fact(
            category="Preferences",
            key="api_preference",
            content="Remember that my API key is SECRET_TEST_KEY_123 and token is sk-9999999999999999999999999999",
        )

        # Content in returned fact must be redacted
        assert "SECRET_TEST_KEY_123" not in fact.content
        assert "[REDACTED" in fact.content

        # Content saved on disk must also be redacted
        file_path = tmp_path / "Preferences" / "api_preference.md"
        raw_disk_content = file_path.read_text(encoding="utf-8")
        assert "SECRET_TEST_KEY_123" not in raw_disk_content


# ---------------------------------------------------------------------------
# 7. Unified MemoryManager and Agent Integration Tests
# ---------------------------------------------------------------------------
class TestMemoryManagerAndAgent:
    def test_memory_manager_commands(self, tmp_path):
        mm = MemoryManager(base_dir=tmp_path, workspace_dir=tmp_path)

        # 1. Remember command
        resp = mm.handle_memory_command("Remember that my favorite beverage is Earl Grey tea.")
        assert resp is not None
        assert "committed that to memory" in resp

        # 2. Query command
        query_resp = mm.handle_memory_command("What do you remember about beverage?")
        assert query_resp is not None
        assert "Earl Grey tea" in query_resp

        # 3. Forget command
        forget_resp = mm.handle_memory_command("Forget favorite_beverage")
        assert forget_resp is not None
        assert "removed" in forget_resp or "forgotten" in forget_resp

    def test_selective_context_injection(self, tmp_path):
        mm = MemoryManager(base_dir=tmp_path, workspace_dir=tmp_path)
        # Store unrelated facts
        mm.semantic.store_fact("Preferences", "color", "User loves navy blue.")
        mm.semantic.store_fact("Projects", "target_model", "Project uses Gemini 3.8 Flash.")
        mm.semantic.store_fact("Profile", "location", "User is located in Bangalore.")

        # Augmented context for a query about AI model
        context = mm.build_augmented_context("What AI model are we configuring?")
        assert "Gemini 3.8 Flash" in context
        # Should NOT dump the entire database
        assert "navy blue" not in context
        assert "Bangalore" not in context

    @pytest.mark.asyncio
    async def test_agent_integration_with_memory(self, tmp_path):
        mock_provider = MagicMock(spec=AIProvider)
        mock_provider.generate = AsyncMock(
            return_value=ModelResponse(text="JARVIS is operating with Google Gemini.")
        )

        mm = MemoryManager(base_dir=tmp_path, workspace_dir=tmp_path)
        mm.semantic.store_fact("Projects", "model_fact", "This project is powered by Google Gemini.")

        agent = JarvisAgent(ai_provider=mock_provider, memory_manager=mm)

        # 1. Direct memory command test
        cmd_response = await agent.process_user_input("Remember that this project uses Gemini rather than Claude.")
        assert "committed that to memory" in cmd_response

        # 2. Query handled by Gemini with injected memory context
        response = await agent.process_user_input("What model does this project use?")
        assert "Google Gemini" in response

        # Verify that generate was called and system_instruction contained the injected fact
        call_kwargs = mock_provider.generate.call_args.kwargs
        system_inst = call_kwargs.get("system_instruction", "")
        assert "Gemini" in system_inst

        # 3. Verify turn was recorded in short-term memory
        turns = mm.short_term.get_turns()
        assert len(turns) >= 2
