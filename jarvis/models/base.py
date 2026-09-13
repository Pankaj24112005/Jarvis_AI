"""Abstract interfaces and data contracts for AI Model Providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class ToolCallRequest:
    """Represents a request from the model to call a specific tool."""

    name: str
    arguments: dict[str, Any]
    id: str | None = None


@dataclass
class ToolDefinition:
    """Metadata and parameter schema defining a tool available to the model."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass
class ModelResponse:
    """Standardized response from an AI Model Provider."""

    text: str = ""
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    raw_response: Any = None
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        """Check whether the model requested any tool executions."""
        return len(self.tool_calls) > 0


class AIProvider(ABC):
    """Abstract interface defining the contract for all AI model providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate a complete text response asynchronously."""
        pass

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream response tokens asynchronously."""
        pass

    @abstractmethod
    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        system_instruction: str | None = None,
        temperature: float | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Generate response with structured function/tool calling capability."""
        pass

    @abstractmethod
    async def analyze_image(
        self,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        system_instruction: str | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Analyze multimodal image content with text prompt."""
        pass

    @abstractmethod
    async def create_embedding(self, text: str, **kwargs: Any) -> list[float]:
        """Create dense vector embeddings for input text."""
        pass
