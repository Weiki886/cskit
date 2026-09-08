from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .errors import CskitDataError


def open_database(path: Path) -> sqlite3.Connection:
    """Open a Codex SQLite database in read-only mode."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise CskitDataError(f"找不到 Codex 数据库：{path}")
    uri = path.as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection
    except sqlite3.Error as exc:
        raise CskitDataError(f"无法以只读模式打开数据库：{exc}") from exc


def load_session_titles(path: Path) -> dict[str, str]:
    """Read the latest UI title for each thread from session_index.jsonl."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return {}
    latest: dict[str, tuple[str, int, str]] = {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                thread_id = value.get("id")
                thread_name = value.get("thread_name")
                updated_at = value.get("updated_at")
                if not isinstance(thread_id, str) or not isinstance(thread_name, str):
                    continue
                thread_name = thread_name.strip()
                if not thread_name:
                    continue
                sort_key = updated_at if isinstance(updated_at, str) else ""
                candidate = (sort_key, line_number, thread_name)
                previous = latest.get(thread_id)
                if previous is None or candidate[:2] > previous[:2]:
                    latest[thread_id] = candidate
    except (OSError, UnicodeError):
        return {}
    return {thread_id: value[2] for thread_id, value in latest.items()}


def load_sidebar_project_names(path: Path) -> dict[str, str]:
    """Map thread IDs to the project names shown in the desktop sidebar."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(state, dict):
        return {}
    assignments = state.get("thread-project-assignments")
    projects = state.get("local-projects")
    if not isinstance(assignments, dict) or not isinstance(projects, dict):
        return {}
    result: dict[str, str] = {}
    for thread_id, assignment in assignments.items():
        if not isinstance(thread_id, str) or not isinstance(assignment, dict):
            continue
        project_id = assignment.get("projectId")
        project = projects.get(project_id) if isinstance(project_id, str) else None
        if not isinstance(project, dict):
            continue
        project_name = project.get("name")
        if isinstance(project_name, str) and project_name.strip():
            result[thread_id] = project_name.strip()
    return result
