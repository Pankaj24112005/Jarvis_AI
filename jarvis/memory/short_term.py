"""Short-term conversational memory with sliding-window and token-aware truncation."""

import time
from dataclasses import asdict, dataclass, field
from typing import Any
from jarvis.utils.logging import logger


@dataclass
class MessageTurn:
    """Represents a single conversational turn between user, assistant, or tool."""

    role: str  # "user", "assistant", "system"
    content: str
    timestamp: float = field(default_factory=time.time)

    @property
    def estimated_tokens(self) -> int:
        """Estimate token count (~4 characters per token heuristic)."""
        return max(1, len(self.content) // 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "estimated_tokens": self.estimated_tokens,
        }


class ShortTermMemory:
    """In-memory sliding window buffer managing conversation history with context limits."""

    def __init__(self, max_turns: int = 20, max_tokens: int = 8000) -> None:
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self._turns: list[MessageTurn] = []

    def add_turn(self, role: str, content: str) -> MessageTurn:
        """Append a new message turn and enforce context limits."""
        turn = MessageTurn(role=role, content=content)
        self._turns.append(turn)
        self._truncate_if_needed()
        return turn

    def get_turns(self, limit: int | None = None) -> list[MessageTurn]:
        """Return the active message turns, optionally limited to recent N turns."""
        if limit and limit > 0:
            return self._turns[-limit:]
        return list(self._turns)

    def get_formatted_context(self, max_tokens: int | None = None, assistant_name: str = "JARVIS") -> str:
        """Assemble turns into a clean conversational dialogue block."""
        target_token_budget = max_tokens or self.max_tokens
        included_turns: list[MessageTurn] = []
        token_count = 0

        # Scan backwards to fit the most recent messages in budget
        for turn in reversed(self._turns):
            cost = turn.estimated_tokens
            if token_count + cost > target_token_budget and included_turns:
                break
            included_turns.insert(0, turn)
            token_count += cost

        lines: list[str] = []
        for turn in included_turns:
            speaker = "User" if turn.role == "user" else assistant_name
            lines.append(f"{speaker}: {turn.content}")

        return "\n".join(lines)

    @property
    def total_estimated_tokens(self) -> int:
        """Sum of estimated tokens in the buffer."""
        return sum(t.estimated_tokens for t in self._turns)

    def _truncate_if_needed(self) -> None:
        """Evict oldest messages if exceeding turn or token limits."""
        # 1. Turn count limit
        if len(self._turns) > self.max_turns:
            excess = len(self._turns) - self.max_turns
            self._turns = self._turns[excess:]
            logger.debug("Truncated %d oldest turns by turn count limit", excess)

        # 2. Token budget limit
        while self._turns and self.total_estimated_tokens > self.max_tokens:
            dropped = self._turns.pop(0)
            logger.debug("Dropped oldest turn (%d tokens) to stay within budget", dropped.estimated_tokens)

    def clear(self) -> None:
        """Reset short-term memory."""
        self._turns.clear()
        logger.debug("Short-term memory cleared.")

    def to_list(self) -> list[dict[str, Any]]:
        """Serialize memory turns."""
        return [t.to_dict() for t in self._turns]

    def from_list(self, data: list[dict[str, Any]]) -> None:
        """Restore memory turns from serialized records."""
        self._turns = [
            MessageTurn(
                role=d.get("role", "user"),
                content=d.get("content", ""),
                timestamp=d.get("timestamp", time.time()),
            )
            for d in data
        ]
        self._truncate_if_needed()
