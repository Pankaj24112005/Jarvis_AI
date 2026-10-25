"""Project Memory and Workspace Awareness inspecting project state, tasks, decisions, and Git."""

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.utils.logging import logger


@dataclass
class ProjectStateInfo:
    """Consolidated project awareness snapshot."""

    project_name: str = "Unknown"
    project_type: str = "general"
    workspace_root: str = ""
    current_branch: str = "unknown"
    latest_commit: str = "none"
    is_git_clean: bool = True
    modified_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    active_phase: str = "in-progress"
    completed_tasks: list[str] = field(default_factory=list)
    pending_tasks: list[str] = field(default_factory=list)
    recent_decisions: list[str] = field(default_factory=list)
    context_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "project_type": self.project_type,
            "workspace_root": self.workspace_root,
            "current_branch": self.current_branch,
            "latest_commit": self.latest_commit,
            "is_git_clean": self.is_git_clean,
            "modified_files": self.modified_files,
            "untracked_files": self.untracked_files,
            "active_phase": self.active_phase,
            "completed_tasks": self.completed_tasks,
            "pending_tasks": self.pending_tasks,
            "recent_decisions": self.recent_decisions,
            "context_notes": self.context_notes,
        }


class ProjectMemory:
    """Inspects workspace state, .jarvis metadata files, and Git status in read-only mode."""

    def __init__(self, workspace_path: str | Path | None = None) -> None:
        self.workspace_path = Path(workspace_path or os.getcwd()).resolve()
        self.dot_jarvis = self.workspace_path / ".jarvis"

    def has_project_state(self) -> bool:
        """Check if .jarvis directory exists in workspace."""
        return self.dot_jarvis.exists() and self.dot_jarvis.is_dir()

    def inspect_git(self) -> dict[str, Any]:
        """Perform strictly read-only inspection of Git status in the workspace."""
        git_info: dict[str, Any] = {
            "is_git": False,
            "branch": "none",
            "commit": "none",
            "is_clean": True,
            "modified": [],
            "untracked": [],
        }

        git_dir = self.workspace_path / ".git"
        if not git_dir.exists():
            return git_info

        try:
            # 1. Branch
            branch_out = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if branch_out.returncode == 0:
                git_info["is_git"] = True
                git_info["branch"] = branch_out.stdout.strip()

            # 2. Latest Commit
            commit_out = subprocess.run(
                ["git", "log", "-1", "--oneline"],
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if commit_out.returncode == 0 and commit_out.stdout.strip():
                git_info["commit"] = commit_out.stdout.strip()

            # 3. Status
            status_out = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(self.workspace_path),
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if status_out.returncode == 0:
                lines = [line.strip() for line in status_out.stdout.splitlines() if line.strip()]
                git_info["is_clean"] = len(lines) == 0
                for line in lines:
                    status_code = line[:2]
                    file_name = line[3:].strip()
                    if status_code.startswith("?") or "??" in status_code:
                        git_info["untracked"].append(file_name)
                    else:
                        git_info["modified"].append(file_name)

        except Exception as ex:
            logger.debug("Git inspection unavailable or timed out: %s", ex)

        return git_info

    def get_project_state(self) -> ProjectStateInfo:
        """Read and consolidate .jarvis metadata and Git status into a ProjectStateInfo object."""
        info = ProjectStateInfo(
            project_name=self.workspace_path.name,
            workspace_root=str(self.workspace_path),
        )

        # 1. Inspect Git
        git = self.inspect_git()
        if git["is_git"]:
            info.current_branch = git["branch"]
            info.latest_commit = git["commit"]
            info.is_git_clean = git["is_clean"]
            info.modified_files = git["modified"]
            info.untracked_files = git["untracked"]

        # 2. Inspect .jarvis/project_state.json
        state_file = self.dot_jarvis / "project_state.json"
        if state_file.exists():
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
                info.project_name = data.get("name", info.project_name)
                info.project_type = data.get("type", info.project_type)
                info.active_phase = data.get("active_phase", info.active_phase)
            except Exception as ex:
                logger.warning("Error reading %s: %s", state_file, ex)

        # 3. Inspect .jarvis/tasks.md
        tasks_file = self.dot_jarvis / "tasks.md"
        if tasks_file.exists():
            try:
                completed, pending = self._parse_tasks_markdown(tasks_file.read_text(encoding="utf-8"))
                info.completed_tasks = completed
                info.pending_tasks = pending
            except Exception as ex:
                logger.warning("Error reading %s: %s", tasks_file, ex)

        # 4. Inspect .jarvis/decisions.md
        decisions_file = self.dot_jarvis / "decisions.md"
        if decisions_file.exists():
            try:
                info.recent_decisions = self._parse_decisions_markdown(decisions_file.read_text(encoding="utf-8"))
            except Exception as ex:
                logger.warning("Error reading %s: %s", decisions_file, ex)

        # 5. Inspect .jarvis/context.md
        context_file = self.dot_jarvis / "context.md"
        if context_file.exists():
            try:
                info.context_notes = context_file.read_text(encoding="utf-8").strip()
            except Exception as ex:
                logger.warning("Error reading %s: %s", context_file, ex)

        return info

    def format_project_context(self, state: ProjectStateInfo | None = None) -> str:
        """Construct a structured project context block for Gemini injection."""
        info = state or self.get_project_state()
        lines = [
            f"### Active Workspace Context: {info.project_name} ({info.project_type})",
            f"- **Branch**: `{info.current_branch}` | **Commit**: `{info.latest_commit}` | **Git Clean**: {info.is_git_clean}",
            f"- **Active Phase**: {info.active_phase}",
        ]

        if info.modified_files:
            lines.append(f"- **Modified Files**: {', '.join(info.modified_files[:10])}")
        if info.untracked_files:
            lines.append(f"- **Untracked Files**: {', '.join(info.untracked_files[:10])}")

        if info.completed_tasks:
            lines.append(f"- **Recently Completed Tasks**: {'; '.join(info.completed_tasks[-4:])}")
        if info.pending_tasks:
            lines.append(f"- **Next Planned Tasks**: {'; '.join(info.pending_tasks[:4])}")

        if info.recent_decisions:
            lines.append(f"- **Key Decisions**: {'; '.join(info.recent_decisions[-3:])}")

        if info.context_notes:
            # First 3 lines or 300 characters of context notes
            summary_notes = info.context_notes.splitlines()[:3]
            lines.append(f"- **Context Notes**: {' '.join(summary_notes)}")

        return "\n".join(lines)

    def get_continuity_summary(self) -> str:
        """Formulate a comprehensive project continuity summary for resuming work."""
        info = self.get_project_state()

        completed_str = "\n".join(f"  ✓ {t}" for t in info.completed_tasks) if info.completed_tasks else "  (None recorded)"
        pending_str = "\n".join(f"  ☐ {t}" for t in info.pending_tasks) if info.pending_tasks else "  (None pending)"
        decisions_str = "\n".join(f"  • {d}" for d in info.recent_decisions[-5:]) if info.recent_decisions else "  (None recorded)"

        git_status_desc = (
            "clean (all changes committed)"
            if info.is_git_clean
            else f"{len(info.modified_files)} modified, {len(info.untracked_files)} untracked files"
        )

        next_task = info.pending_tasks[0] if info.pending_tasks else "Determine next milestone with the user."

        return (
            f"Project Continuity Report for '{info.project_name}':\n\n"
            f"Current Branch: {info.current_branch} (commit: {info.latest_commit})\n"
            f"Working Tree Status: {git_status_desc}\n"
            f"Active Phase: {info.active_phase}\n\n"
            f"Completed Milestones:\n{completed_str}\n\n"
            f"Upcoming Tasks:\n{pending_str}\n\n"
            f"Recent Architectural Decisions:\n{decisions_str}\n\n"
            f"Next Logical Task: {next_task}"
        )

    def _parse_tasks_markdown(self, text: str) -> tuple[list[str], list[str]]:
        """Parse tasks into completed ([x]) and pending ([ ]) lists."""
        completed: list[str] = []
        pending: list[str] = []

        for line in text.splitlines():
            line = line.strip()
            if line.startswith("- [x]") or line.startswith("* [x]"):
                completed.append(line[5:].strip())
            elif line.startswith("- [ ]") or line.startswith("* [ ]"):
                pending.append(line[5:].strip())

        return completed, pending

    def _parse_decisions_markdown(self, text: str) -> list[str]:
        """Extract recorded decisions from markdown list or headers."""
        decisions: list[str] = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                decisions.append(line[2:].strip())
            elif line.startswith("### "):
                decisions.append(line[4:].strip())
        return decisions
