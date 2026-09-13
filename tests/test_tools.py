"""Unit tests for Standardized Tool Framework, Built-in Tools, and Registry Execution."""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from jarvis.core.agent import JarvisAgent
from jarvis.models.base import AIProvider, ModelResponse, ToolCallRequest, ToolDefinition
from jarvis.security.permissions import (
    AuditLogger,
    PermissionController,
    PermissionLevel,
)
from jarvis.tools.base import BaseTool, ToolResult
from jarvis.tools.filesystem import (
    DeleteFileTool,
    ListDirTool,
    ModifyFileTool,
    PathSecurityError,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
    resolve_safe_path,
)
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.terminal import TerminalExecuteTool


class DummyEchoTool(BaseTool):
    """Dummy tool for registry and execution testing."""

    name = "dummy_echo"
    description = "Echoes back the provided message."
    permission_level = PermissionLevel.SAFE

    @property
    def parameters_schema(self):
        return {
            "type": "OBJECT",
            "properties": {"message": {"type": "STRING"}},
            "required": ["message"],
        }

    async def execute(self, message: str, **kwargs):
        return ToolResult(success=True, result={"echo": message})


# ==============================================================================
# 1. Registry Tests
# ==============================================================================

def test_registry_register_and_lookup():
    """Verify tool registration, lookup, listing, and schema export."""
    registry = ToolRegistry()
    tool = DummyEchoTool()
    registry.register(tool)

    assert registry.get("dummy_echo") is tool
    assert len(registry.list_tools()) == 1

    # Gemini tool schema export
    gemini_tools = registry.get_gemini_tools()
    assert len(gemini_tools) == 1
    assert gemini_tools[0].function_declarations[0].name == "dummy_echo"

    # Unregister
    assert registry.unregister("dummy_echo")
    assert registry.get("dummy_echo") is None


@pytest.mark.asyncio
async def test_registry_execution_pipeline(tmp_path: Path):
    """Verify registry validates arguments, checks permission, and executes."""
    registry = ToolRegistry()
    registry.register(DummyEchoTool())
    controller = PermissionController(audit_logger=AuditLogger(log_path=str(tmp_path / "audit.log")))

    # Successful execution
    res = await registry.execute("dummy_echo", {"message": "Hello World"}, controller)
    assert res.success
    assert res.result == {"echo": "Hello World"}

    # Validation failure: missing required argument
    bad_res = await registry.execute("dummy_echo", {}, controller)
    assert not bad_res.success
    assert "Missing required parameter 'message'" in bad_res.error

    # Missing tool
    missing_res = await registry.execute("non_existent_tool", {}, controller)
    assert not missing_res.success
    assert "not registered" in missing_res.error


# ==============================================================================
# 2. Filesystem Tools & Boundary Tests
# ==============================================================================

def test_filesystem_path_traversal_prevention(tmp_path: Path):
    """Ensure path traversal attacks targeting locations outside workspace are rejected."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Valid relative path inside workspace
    safe = resolve_safe_path("sub/file.txt", workspace)
    assert safe == (workspace / "sub" / "file.txt").resolve()

    # Malicious traversal attempts outside workspace
    with pytest.raises(PathSecurityError):
        resolve_safe_path("../../Windows/System32", workspace)

    with pytest.raises(PathSecurityError):
        resolve_safe_path("../secret.txt", workspace)


@pytest.mark.asyncio
async def test_filesystem_crud_lifecycle(tmp_path: Path):
    """Verify full CRUD lifecycle within permitted workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    write_tool = WriteFileTool(workspace_root=workspace)
    read_tool = ReadFileTool(workspace_root=workspace)
    modify_tool = ModifyFileTool(workspace_root=workspace)
    list_tool = ListDirTool(workspace_root=workspace)
    search_tool = SearchFilesTool(workspace_root=workspace)
    delete_tool = DeleteFileTool(workspace_root=workspace)

    # 1. Write file
    w_res = await write_tool.execute(path="notes/hello.txt", content="Initial Content")
    assert w_res.success

    # 2. Read file
    r_res = await read_tool.execute(path="notes/hello.txt")
    assert r_res.success
    assert r_res.result["content"] == "Initial Content"

    # 3. Modify file
    m_res = await modify_tool.execute(path="notes/hello.txt", target="Initial", replacement="Updated")
    assert m_res.success

    r_res2 = await read_tool.execute(path="notes/hello.txt")
    assert r_res2.result["content"] == "Updated Content"

    # 4. Search file
    s_res = await search_tool.execute(pattern="*.txt", content_query="Updated")
    assert s_res.success
    assert "notes/hello.txt" in s_res.result["matches"]

    # 5. List directory
    l_res = await list_tool.execute(path="notes")
    assert l_res.success
    assert any(e["name"] == "hello.txt" for e in l_res.result["entries"])

    # 6. Delete file
    d_res = await delete_tool.execute(path="notes/hello.txt")
    assert d_res.success
    assert not (workspace / "notes" / "hello.txt").exists()


# ==============================================================================
# 3. Terminal Tool & Safety Classification Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_terminal_safe_command_execution():
    """Verify executing safe terminal command captures stdout and exit code."""
    term_tool = TerminalExecuteTool(default_timeout=5.0)

    # Safe command check
    assert term_tool.classify_command("python --version") == PermissionLevel.LOW_RISK

    res = await term_tool.execute("python -c \"print('terminal_ok')\"")
    assert res.success
    assert "terminal_ok" in res.result["stdout"]
    assert res.result["exit_code"] == 0


def test_terminal_dangerous_command_classification():
    """Verify dangerous commands are classified as HIGH_RISK."""
    term_tool = TerminalExecuteTool()
    assert term_tool.classify_command("del /f /q C:\\somefile") == PermissionLevel.HIGH_RISK
    assert term_tool.classify_command("rmdir /s /q testdir") == PermissionLevel.HIGH_RISK
    assert term_tool.classify_command("format d:") == PermissionLevel.HIGH_RISK
    assert term_tool.classify_command("shutdown /s /t 0") == PermissionLevel.HIGH_RISK


@pytest.mark.asyncio
async def test_terminal_timeout_handling():
    """Verify long-running commands time out and are terminated."""
    term_tool = TerminalExecuteTool()
    res = await term_tool.execute("python -c \"import time; time.sleep(5)\"", timeout=1)
    assert not res.success
    assert "timed out" in res.error


# ==============================================================================
# 4. Agent Multi-Turn Tool Integration & Loop Protection
# ==============================================================================

@pytest.mark.asyncio
async def test_agent_tool_calling_loop(tmp_path: Path):
    """Verify agent invokes tools, handles results, and returns final answer."""
    registry = ToolRegistry()
    registry.register(DummyEchoTool())
    controller = PermissionController(audit_logger=AuditLogger(log_path=str(tmp_path / "audit.log")))

    class MockToolModelProvider(AIProvider):
        def __init__(self):
            self.turn = 0

        async def generate(self, prompt: str, **kwargs):
            self.turn += 1
            if self.turn == 1:
                # Model requests dummy_echo tool
                return ModelResponse(
                    text="Calling echo",
                    tool_calls=[ToolCallRequest(name="dummy_echo", arguments={"message": "AgentTest"})],
                )
            return ModelResponse(text="Echo finished successfully.")

        async def stream(self, prompt: str, **kwargs):
            yield "stream"

        async def generate_with_tools(self, prompt: str, tools: list, **kwargs):
            return await self.generate(prompt, **kwargs)

        async def analyze_image(self, prompt: str, image_bytes: bytes, **kwargs):
            return ModelResponse()

        async def create_embedding(self, text: str, **kwargs):
            return []

    agent = JarvisAgent(
        ai_provider=MockToolModelProvider(),
        tool_registry=registry,
        permission_controller=controller,
    )

    response = await agent.process_user_input("Run dummy echo")
    assert "dummy_echo: success" in response
