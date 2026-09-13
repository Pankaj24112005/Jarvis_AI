"""Central Tool Registry managing discovery, validation, and authorized execution."""

import asyncio
import time
from typing import Any
from google.genai import types

from jarvis.models.base import ToolDefinition
from jarvis.security.permissions import (
    PermissionController,
    PermissionLevel,
    default_permission_controller,
)
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.utils.logging import logger


class ToolRegistry:
    """Registry maintaining available tools and mediating authorized execution."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a new tool instance."""
        if not tool.name:
            raise ValueError("Tool name cannot be empty")
        if tool.name in self._tools:
            logger.debug("Overwriting existing tool registration: %s", tool.name)
        self._tools[tool.name] = tool
        logger.debug("Registered tool: %s (Level %d)", tool.name, int(tool.permission_level))

    def unregister(self, name: str) -> bool:
        """Remove a tool from registry."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> BaseTool | None:
        """Retrieve a registered tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def get_tool_definitions(self) -> list[ToolDefinition]:
        """Export tool definitions for model providers."""
        return [tool.get_tool_definition() for tool in self._tools.values()]

    def get_gemini_tools(self) -> list[types.Tool]:
        """Generate Google GenAI Tool structures for registered tools."""
        declarations = [tool.to_gemini_function_declaration() for tool in self._tools.values()]
        if declarations:
            return [types.Tool(function_declarations=declarations)]
        return []

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        permission_controller: PermissionController | None = None,
    ) -> ToolResult:
        """Validate, authorize, and execute a tool safely with audit logging."""
        controller = permission_controller or default_permission_controller
        start_time = time.time()

        tool = self.get(tool_name)
        if not tool:
            err = f"Tool '{tool_name}' is not registered."
            logger.warning(err)
            controller.audit_logger.log(
                tool_name=tool_name,
                arguments=arguments,
                level=PermissionLevel.SAFE,
                approved=False,
                error=err,
            )
            return ToolResult(success=False, error=err)

        # 1. Validate arguments
        is_valid, validation_err = tool.validate_arguments(arguments)
        if not is_valid:
            err = f"Argument validation failed for '{tool_name}': {validation_err}"
            logger.warning(err)
            controller.audit_logger.log(
                tool_name=tool_name,
                arguments=arguments,
                level=tool.permission_level,
                approved=False,
                error=err,
            )
            return ToolResult(success=False, error=err)

        # 2. Check permissions & Human Authorization
        decision = await controller.check_and_authorize(
            tool_name=tool.name,
            arguments=arguments,
            level=tool.permission_level,
            description=tool.description,
        )

        if not decision.is_approved:
            err = f"Permission denied for '{tool_name}': {decision.reason}"
            logger.info("Execution denied: %s", err)
            controller.audit_logger.log(
                tool_name=tool_name,
                arguments=arguments,
                level=tool.permission_level,
                approved=False,
                duration_ms=(time.time() - start_time) * 1000,
                error=err,
            )
            return ToolResult(success=False, error=err)

        # 3. Execute with timeout
        try:
            result = await asyncio.wait_for(
                tool.execute(**arguments),
                timeout=tool.timeout_seconds,
            )
            duration_ms = (time.time() - start_time) * 1000
            controller.audit_logger.log(
                tool_name=tool_name,
                arguments=arguments,
                level=tool.permission_level,
                approved=True,
                duration_ms=duration_ms,
                result=result.result,
                error=result.error,
            )
            return result

        except asyncio.TimeoutError:
            err = f"Tool '{tool_name}' timed out after {tool.timeout_seconds} seconds."
            logger.error(err)
            controller.audit_logger.log(
                tool_name=tool_name,
                arguments=arguments,
                level=tool.permission_level,
                approved=True,
                duration_ms=(time.time() - start_time) * 1000,
                error=err,
            )
            return ToolResult(success=False, error=err)

        except Exception as ex:
            err = f"Tool execution failed for '{tool_name}': {str(ex)}"
            logger.error(err, exc_info=True)
            controller.audit_logger.log(
                tool_name=tool_name,
                arguments=arguments,
                level=tool.permission_level,
                approved=True,
                duration_ms=(time.time() - start_time) * 1000,
                error=err,
            )
            return ToolResult(success=False, error=err)


# Global default registry
default_tool_registry = ToolRegistry()
