"""Abstract Base Tool definition and execution contracts."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from google.genai import types

from jarvis.models.base import ToolDefinition
from jarvis.security.permissions import PermissionLevel
from jarvis.utils.logging import logger


@dataclass
class ToolResult:
    """Structured, standardized execution result returned to model and audit system."""

    success: bool
    result: Any = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert result into serializable dictionary for model consumption."""
        data: dict[str, Any] = {
            "success": self.success,
        }
        if self.success:
            data["result"] = self.result
        else:
            data["error"] = self.error
        if self.metadata:
            data["metadata"] = self.metadata
        return data


class BaseTool(ABC):
    """Abstract base class for all JARVIS tools."""

    name: str = ""
    description: str = ""
    permission_level: PermissionLevel = PermissionLevel.SAFE
    timeout_seconds: float = 30.0

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """Return JSON Schema describing the expected parameters."""
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool's core logic asynchronously with arguments."""
        pass

    def get_tool_definition(self) -> ToolDefinition:
        """Return a model-agnostic ToolDefinition object."""
        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )

    def to_gemini_function_declaration(self) -> types.FunctionDeclaration:
        """Convert this tool into Google GenAI FunctionDeclaration."""
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=self.parameters_schema,
        )

    def validate_arguments(self, arguments: dict[str, Any]) -> tuple[bool, str | None]:
        """Validate input arguments against declared schema."""
        schema = self.parameters_schema
        required_keys = schema.get("required", [])
        for req in required_keys:
            if req not in arguments:
                return False, f"Missing required parameter '{req}'"
        return True, None
