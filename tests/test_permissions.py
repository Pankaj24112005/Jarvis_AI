"""Unit tests for 5-Tier Permission Controller and Audit Logging."""

import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from jarvis.security.permissions import (
    AuditLogger,
    PermissionController,
    PermissionDecision,
    PermissionLevel,
)


@pytest.fixture
def temp_audit_log(tmp_path: Path):
    """Provides a temporary audit log path for testing."""
    return tmp_path / "audit_test.log"


# ==============================================================================
# 1. Permission Level Authorization Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_permission_level_0_auto_approved(temp_audit_log: Path):
    """Level 0 (SAFE) must be auto-approved without human prompt."""
    mock_callback = AsyncMock(return_value=False)
    controller = PermissionController(
        confirmation_threshold=3,
        approval_callback=mock_callback,
        audit_logger=AuditLogger(log_path=str(temp_audit_log)),
    )

    decision = await controller.check_and_authorize(
        tool_name="test_safe_tool",
        arguments={},
        level=PermissionLevel.SAFE,
        description="Harmless query",
    )

    assert decision.is_approved
    assert "Auto-approved" in decision.reason
    mock_callback.assert_not_called()


@pytest.mark.asyncio
async def test_permission_level_1_and_2_auto_approved(temp_audit_log: Path):
    """Levels 1 and 2 below confirmation threshold (3) must be auto-approved."""
    mock_callback = AsyncMock(return_value=False)
    controller = PermissionController(
        confirmation_threshold=3,
        approval_callback=mock_callback,
        audit_logger=AuditLogger(log_path=str(temp_audit_log)),
    )

    dec_1 = await controller.check_and_authorize(
        tool_name="list_dir",
        arguments={"path": "."},
        level=PermissionLevel.LOW_RISK,
    )
    assert dec_1.is_approved
    mock_callback.assert_not_called()

    dec_2 = await controller.check_and_authorize(
        tool_name="write_file",
        arguments={"path": "test.txt", "content": "hi"},
        level=PermissionLevel.MODERATE,
    )
    assert dec_2.is_approved
    mock_callback.assert_not_called()


@pytest.mark.asyncio
async def test_permission_level_3_confirmation_approved(temp_audit_log: Path):
    """Level 3 (HIGH RISK) requires human confirmation; approves when user says yes."""
    mock_callback = AsyncMock(return_value=True)
    controller = PermissionController(
        confirmation_threshold=3,
        approval_callback=mock_callback,
        audit_logger=AuditLogger(log_path=str(temp_audit_log)),
    )

    decision = await controller.check_and_authorize(
        tool_name="delete_file",
        arguments={"path": "important.txt"},
        level=PermissionLevel.HIGH_RISK,
        description="Delete file from disk",
    )

    assert decision.is_approved
    assert "Explicitly authorized" in decision.reason
    mock_callback.assert_called_once_with(
        "delete_file",
        {"path": "important.txt"},
        PermissionLevel.HIGH_RISK,
        "Delete file from disk",
    )


@pytest.mark.asyncio
async def test_permission_level_3_confirmation_denied(temp_audit_log: Path):
    """Level 3 (HIGH RISK) rejects execution when user denies prompt."""
    mock_callback = AsyncMock(return_value=False)
    controller = PermissionController(
        confirmation_threshold=3,
        approval_callback=mock_callback,
        audit_logger=AuditLogger(log_path=str(temp_audit_log)),
    )

    decision = await controller.check_and_authorize(
        tool_name="delete_file",
        arguments={"path": "important.txt"},
        level=PermissionLevel.HIGH_RISK,
    )

    assert not decision.is_approved
    assert "DENIED" in decision.reason
    mock_callback.assert_called_once()


@pytest.mark.asyncio
async def test_permission_level_4_always_requires_confirmation(temp_audit_log: Path):
    """Level 4 (CRITICAL) must always require confirmation regardless of threshold."""
    mock_callback = AsyncMock(return_value=False)
    # Even if threshold is set abnormally high to 5
    controller = PermissionController(
        confirmation_threshold=5,
        approval_callback=mock_callback,
        audit_logger=AuditLogger(log_path=str(temp_audit_log)),
    )

    decision = await controller.check_and_authorize(
        tool_name="critical_system_tool",
        arguments={"action": "reboot"},
        level=PermissionLevel.CRITICAL,
    )

    assert not decision.is_approved
    mock_callback.assert_called_once()


# ==============================================================================
# 2. Audit Logging & Sanitization Tests
# ==============================================================================

def test_audit_logger_records_and_redacts(temp_audit_log: Path):
    """Verify audit logger writes structured JSON and redacts sensitive data."""
    audit_logger = AuditLogger(log_path=str(temp_audit_log))

    raw_args = {
        "command": "git push",
        "api_key": "AIzaSySecretShouldNeverAppear12345",
        "nested": {"user_password": "super_secret_password"},
        "safe_arg": "public_data",
    }

    audit_logger.log(
        tool_name="terminal_execute",
        arguments=raw_args,
        level=PermissionLevel.HIGH_RISK,
        approved=True,
        duration_ms=45.2,
        result={"exit_code": 0},
    )

    assert temp_audit_log.exists()
    content = temp_audit_log.read_text(encoding="utf-8").strip()
    entry = json.loads(content)

    assert entry["tool"] == "terminal_execute"
    assert entry["level"] == 3
    assert entry["approved"] is True
    assert entry["arguments"]["safe_arg"] == "public_data"
    # Verify sensitive data was redacted
    assert entry["arguments"]["api_key"] == "[REDACTED]"
    assert entry["arguments"]["nested"]["user_password"] == "[REDACTED]"
    assert "super_secret_password" not in content
    assert "AIzaSySecret" not in content
