"""Episodic Memory storing significant events, milestones, and task outcomes in daily Markdown logs."""

import datetime
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from jarvis.memory.security import redact_secrets
from jarvis.utils.logging import logger


@dataclass
class EpisodeEntry:
    """Represents an individual episodic memory entry."""

    timestamp: str  # ISO or readable timestamp (e.g. 2026-09-13 14:30:00)
    session_id: str
    user_request: str
    result_summary: str
    decisions: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    significance_reason: str = "general_interaction"
    significance_score: int = 1  # 1 to 5

    def to_markdown(self) -> str:
        """Render entry as clean GitHub Markdown."""
        lines = [
            f"### [{self.timestamp}] {self.user_request[:80]}",
            f"- **Session**: `{self.session_id}`",
            f"- **User Request**: {self.user_request}",
            f"- **Summary / Result**: {self.result_summary}",
        ]
        if self.decisions:
            lines.append(f"- **Decisions**: {'; '.join(self.decisions)}")
        if self.tools_used:
            lines.append(f"- **Tools Used**: {', '.join(self.tools_used)}")
        if self.significance_reason:
            lines.append(f"- **Significance**: {self.significance_reason} (Score: {self.significance_score})")
        lines.append("")
        return "\n".join(lines)


class EpisodicMemory:
    """Manages long-term episodic interactions saved in date-based Markdown documents."""

    def __init__(self, base_dir: str | Path = "memory/episodes") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def is_significant(
        self,
        user_request: str,
        result_summary: str,
        tools_used: list[str] | None = None,
        decisions: list[str] | None = None,
        significance_override: int | None = None,
    ) -> tuple[bool, str, int]:
        """Determine whether a turn or event is worth persisting long-term.

        Returns (is_significant, reason, score).
        """
        if significance_override is not None:
            return significance_override >= 2, "explicit_override", significance_override

        score = 0
        reasons = []

        # 1. Tool execution indicates state modification or system interaction
        if tools_used:
            score += 2
            reasons.append(f"executed_tools({','.join(tools_used)})")

        # 2. Key architectural, code, or preference decisions
        if decisions:
            score += 2
            reasons.append("recorded_decisions")

        # 3. Explicit memory or instruction keywords
        req_lower = user_request.lower()
        if any(w in req_lower for w in ["remember", "prefer", "always", "never", "configure", "project", "deploy", "build"]):
            score += 2
            reasons.append("key_directive")

        # 4. Long or rich result indicating comprehensive work
        if len(result_summary) > 250:
            score += 1
            reasons.append("substantive_output")

        # Casual short greetings or trivial affirmations should not be persisted
        if any(req_lower == g for g in ["hi", "hello", "hey", "thanks", "thank you", "ok", "cool"]):
            return False, "trivial_greeting", 0

        is_sig = score >= 2
        reason = " + ".join(reasons) if reasons else "routine_turn"
        return is_sig, reason, score

    def log_episode(
        self,
        user_request: str,
        result_summary: str,
        session_id: str = "default",
        tools_used: list[str] | None = None,
        decisions: list[str] | None = None,
        significance_score: int | None = None,
        force: bool = False,
    ) -> EpisodeEntry | None:
        """Evaluate and persist significant event to memory/episodes/YYYY-MM-DD.md."""
        tools = tools_used or []
        decs = decisions or []

        is_sig, reason, score = self.is_significant(
            user_request=user_request,
            result_summary=result_summary,
            tools_used=tools,
            decisions=decs,
            significance_override=significance_score,
        )

        if not is_sig and not force:
            logger.debug("Turn deemed non-significant (score=%d). Skipping episodic persistence.", score)
            return None

        # Redact secrets before saving
        clean_request = redact_secrets(user_request.strip())
        clean_summary = redact_secrets(result_summary.strip())
        clean_decisions = [redact_secrets(d) for d in decs]

        now = datetime.datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")

        entry = EpisodeEntry(
            timestamp=f"{date_str} {time_str}",
            session_id=session_id,
            user_request=clean_request,
            result_summary=clean_summary,
            decisions=clean_decisions,
            tools_used=tools,
            significance_reason=reason,
            significance_score=score,
        )

        file_path = self.base_dir / f"{date_str}.md"
        file_exists = file_path.exists()

        try:
            with open(file_path, "a", encoding="utf-8") as f:
                if not file_exists:
                    f.write(f"# JARVIS Episodes — {date_str}\n\n")
                f.write(entry.to_markdown())
            logger.info("Persisted episodic memory to %s (reason: %s)", file_path, reason)
            return entry
        except Exception as ex:
            logger.error("Failed to write episodic memory log to %s: %s", file_path, ex)
            return None

    def get_recent_episodes(self, days: int = 7, limit: int = 10) -> list[EpisodeEntry]:
        """Load recent episode entries from the latest daily logs."""
        entries: list[EpisodeEntry] = []
        if not self.base_dir.exists():
            return entries

        # List markdown files sorted in reverse date order
        md_files = sorted(self.base_dir.glob("????-??-??.md"), reverse=True)
        recent_files = md_files[:days]

        for file_path in recent_files:
            try:
                content = file_path.read_text(encoding="utf-8")
                parsed = self._parse_episodes_from_markdown(content)
                entries.extend(parsed)
                if len(entries) >= limit:
                    break
            except Exception as ex:
                logger.warning("Error reading episodic log %s: %s", file_path, ex)

        return entries[:limit]

    def search_episodes(self, query: str, limit: int = 5) -> list[EpisodeEntry]:
        """Search episodes for matching query keywords."""
        terms = [t.lower() for t in query.split() if len(t) > 2]
        if not terms:
            return []

        all_episodes = self.get_recent_episodes(days=30, limit=50)
        scored: list[tuple[int, EpisodeEntry]] = []

        for ep in all_episodes:
            text = f"{ep.user_request} {ep.result_summary} {' '.join(ep.decisions)}".lower()
            score = sum(1 for t in terms if t in text)
            if score > 0:
                scored.append((score, ep))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [ep for _, ep in scored[:limit]]

    def format_episodes_context(self, episodes: list[EpisodeEntry], max_tokens: int = 600) -> str:
        """Format selected episodes as concise context lines for prompt injection."""
        if not episodes:
            return ""

        lines = ["### Recent Relevant Past Interactions:"]
        approx_tokens = 0

        for ep in episodes:
            line = f"- [{ep.timestamp}] Task: {ep.user_request} -> Outcome: {ep.result_summary[:120]}"
            if ep.decisions:
                line += f" (Decisions: {'; '.join(ep.decisions)})"
            tokens = len(line) // 4
            if approx_tokens + tokens > max_tokens:
                break
            lines.append(line)
            approx_tokens += tokens

        return "\n".join(lines)

    def _parse_episodes_from_markdown(self, markdown_text: str) -> list[EpisodeEntry]:
        """Parse EpisodeEntry records from formatted markdown text."""
        entries: list[EpisodeEntry] = []
        chunks = re.split(r"\n(?=### \[)", markdown_text)

        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk.startswith("### ["):
                continue

            header_match = re.search(r"### \[(.*?)\] (.*)", chunk)
            timestamp = header_match.group(1) if header_match else "unknown"

            session_match = re.search(r"- \*\*Session\*\*: `(.*?)`", chunk)
            session_id = session_match.group(1) if session_match else "default"

            req_match = re.search(r"- \*\*User Request\*\*: (.*)", chunk)
            user_request = req_match.group(1).strip() if req_match else ""

            res_match = re.search(r"- \*\*Summary / Result\*\*: (.*)", chunk)
            result_summary = res_match.group(1).strip() if res_match else ""

            decs_match = re.search(r"- \*\*Decisions\*\*: (.*)", chunk)
            decisions = [d.strip() for d in decs_match.group(1).split(";")] if decs_match else []

            tools_match = re.search(r"- \*\*Tools Used\*\*: (.*)", chunk)
            tools = [t.strip() for t in tools_match.group(1).split(",")] if tools_match else []

            sig_match = re.search(r"- \*\*Significance\*\*: (.*?) \(Score: (\d+)\)", chunk)
            sig_reason = sig_match.group(1) if sig_match else "logged"
            sig_score = int(sig_match.group(2)) if sig_match else 1

            if user_request or result_summary:
                entries.append(
                    EpisodeEntry(
                        timestamp=timestamp,
                        session_id=session_id,
                        user_request=user_request,
                        result_summary=result_summary,
                        decisions=decisions,
                        tools_used=tools,
                        significance_reason=sig_reason,
                        significance_score=sig_score,
                    )
                )

        return entries
