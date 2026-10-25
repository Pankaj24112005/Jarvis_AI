"""Unified Memory Manager coordinating Short-Term, Working, Episodic, Semantic, and Project Memory."""

import os
import re
from pathlib import Path
from typing import Any

from jarvis.memory.episodic import EpisodicMemory
from jarvis.memory.project import ProjectMemory, ProjectStateInfo
from jarvis.memory.security import contains_secrets, redact_secrets
from jarvis.memory.semantic import MemoryFact, SemanticMemory
from jarvis.memory.short_term import MessageTurn, ShortTermMemory
from jarvis.memory.working import TaskState, WorkingMemory
from jarvis.utils.logging import logger


class MemoryManager:
    """Unified coordinator for all 5 memory tiers and workspace awareness."""

    def __init__(
        self,
        base_dir: str | Path = "memory",
        workspace_dir: str | Path | None = None,
        max_short_term_turns: int = 20,
        max_short_term_tokens: int = 6000,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.short_term = ShortTermMemory(max_turns=max_short_term_turns, max_tokens=max_short_term_tokens)
        self.working = WorkingMemory()
        self.episodic = EpisodicMemory(base_dir=self.base_dir / "episodes")
        self.semantic = SemanticMemory(vault_dir=self.base_dir)
        self.project = ProjectMemory(workspace_path=workspace_dir)

    def build_augmented_context(self, user_query: str, max_tokens: int = 1500) -> str:
        """Retrieve top relevant memories and project context to inject into model prompt."""
        context_blocks: list[str] = []
        token_count = 0

        # 1. Active Task Working Memory (highest priority if active)
        if self.working.is_active:
            working_summary = self.working.get_summary()
            if working_summary:
                block = f"### Active Task Working State:\n{working_summary}"
                context_blocks.append(block)
                token_count += len(block) // 4

        # 2. Relevant Semantic Facts (scored ranking, top 3-5 facts only)
        relevant_facts = self.semantic.search(query=user_query, top_k=4)
        if relevant_facts:
            semantic_block = self.semantic.format_semantic_context(relevant_facts, max_tokens=500)
            if semantic_block:
                context_blocks.append(semantic_block)
                token_count += len(semantic_block) // 4

        # 3. Project Memory Context
        query_lower = user_query.lower()
        project_related_words = ["project", "git", "task", "status", "branch", "code", "file", "build", "state", "continuity", "workspace"]
        is_project_query = any(w in query_lower for w in project_related_words)

        if is_project_query and self.project.has_project_state():
            project_block = self.project.format_project_context()
            if project_block:
                context_blocks.append(project_block)
                token_count += len(project_block) // 4

        # 4. Relevant Episodic Memories (top 2 recent events matching keywords)
        episodes = self.episodic.search_episodes(query=user_query, limit=2)
        if episodes:
            episodic_block = self.episodic.format_episodes_context(episodes, max_tokens=300)
            if episodic_block:
                context_blocks.append(episodic_block)

        if not context_blocks:
            return ""

        return "\n\n".join(context_blocks)

    def handle_memory_command(self, user_input: str) -> str | None:
        """Identify and handle explicit user memory commands.

        Returns a direct response string if handled, or None to proceed with model reasoning.
        """
        text = user_input.strip()
        text_lower = text.lower()

        # 1. Remember command: "Remember that ...", "Remember: ..."
        remember_match = re.match(r"^remember\s+(?:that\s+)?(.*)", text, re.IGNORECASE)
        if remember_match:
            fact_text = remember_match.group(1).strip()
            if fact_text:
                # Determine category and key heuristically
                category = "Knowledge"
                if any(w in fact_text.lower() for w in ["prefer", "like", "favorite", "style", "format"]):
                    category = "Preferences"
                elif any(w in fact_text.lower() for w in ["project", "repo", "codebase", "architecture", "model", "gemini"]):
                    category = "Projects"
                elif any(w in fact_text.lower() for w in ["name", "am", "i am", "developer", "engineer", "user"]):
                    category = "Profile"

                # Generate a short slug key from the first few words
                words = [w for w in re.sub(r"[^\w\s]", "", fact_text.lower()).split() if len(w) > 2]
                key = "_".join(words[:4]) or "user_fact"

                fact = self.semantic.store_fact(category=category, key=key, content=fact_text)
                return f"I have committed that to memory under [{fact.category}/{fact.key}]: '{fact.content}'."

        # 2. Query command: "What do you remember about ..."
        query_match = re.match(r"^what do you remember about\s+(.*)", text, re.IGNORECASE)
        if query_match:
            topic = query_match.group(1).strip().rstrip("?.")
            facts = self.semantic.search(query=topic, top_k=5)
            if facts:
                items = [f"- [{f.category}/{f.key}]: {f.content}" for f in facts]
                return f"Here is what I remember regarding '{topic}':\n" + "\n".join(items)
            return f"I don't currently have any specific saved memories about '{topic}'."

        # 3. Forget command: "Forget [category/]key", "Forget that X"
        forget_match = re.match(r"^forget\s+(?:that\s+)?(.*)", text, re.IGNORECASE)
        if forget_match:
            target = forget_match.group(1).strip().rstrip("?.")
            # Try to match key directly
            found = False
            for cat in ["Profile", "Projects", "Preferences", "Skills", "Knowledge"]:
                if self.semantic.forget_fact(category=cat, key=target):
                    found = True
                    return f"I have removed the memory for '{target}' from {cat}."

            # If not found directly by slug, search for top match
            matches = self.semantic.search(query=target, top_k=1)
            if matches:
                top = matches[0]
                self.semantic.forget_fact(category=top.category, key=top.key)
                return f"I have forgotten [{top.category}/{top.key}]: '{top.content}'."

            return f"I could not find a stored memory matching '{target}' to forget."

        # 4. Continuity command: "Continue the project...", "inspect project state"
        if any(phrase in text_lower for phrase in [
            "continue the project from where we stopped",
            "continue the project",
            "inspect this project and tell me its current development state",
            "inspect project",
            "what is the current project state",
        ]):
            return self.project.get_continuity_summary()

        return None

    def record_turn(
        self,
        user_input: str,
        assistant_response: str,
        tools_used: list[str] | None = None,
        decisions: list[str] | None = None,
        session_id: str = "default",
    ) -> None:
        """Record turn in short-term buffer and evaluate episodic significance."""
        # 1. Update short-term conversational buffer
        self.short_term.add_turn(role="user", content=user_input)
        self.short_term.add_turn(role="assistant", content=assistant_response)

        # 2. Update working memory if active
        if self.working.is_active:
            if decisions:
                for dec in decisions:
                    self.working.record_decision(dec)
            if tools_used:
                for tool in tools_used:
                    self.working.record_tool_result(tool, "completed")

        # 3. Log to episodic memory if significant
        self.episodic.log_episode(
            user_request=user_input,
            result_summary=assistant_response[:300],
            session_id=session_id,
            tools_used=tools_used,
            decisions=decisions,
        )


# Global default instance
default_memory_manager = MemoryManager()
