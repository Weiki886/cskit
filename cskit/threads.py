from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import CskitDataError


# The union of what exportcode and clonecode each required. Callers that only
# need a subset pass `required_columns` so their error behaviour on older Codex
# schemas stays identical to the standalone scripts.
UNION_REQUIRED_COLUMNS = frozenset({
    "id", "title", "cwd", "model_provider", "model", "history_mode",
    "archived", "thread_source", "updated_at_ms", "rollout_path",
})

EXPORT_REQUIRED_COLUMNS = frozenset({
    "id", "rollout_path", "title", "archived", "thread_source",
})


@dataclass(frozen=True)
class ThreadRecord:
    """A user-owned Codex thread as shown in the desktop sidebar.

    `display_name` is what the list UI shows; `full_name` prefers the name
    Codex itself stores, because the session index copy can be shortened for
    display and `title` holds a raw first-message dump.
    """

    id: str
    display_name: str
    full_name: str
    rollout_path: Path
    project_name: str = "独立任务"
    created_at_ms: int = 0
    updated_at_ms: int = 0
    cwd: str = ""
    model_provider: str = ""
    model: str = ""
    history_mode: str = ""
    row: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


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


def list_threads(
    state_db: Path,
    *,
    session_titles: dict[str, str] | None = None,
    project_names: dict[str, str] | None = None,
    sidebar_only: bool = False,
    max_per_project: int | None = None,
    required_columns: frozenset[str] | set[str] | None = None,
) -> list[ThreadRecord]:
    """List user-owned, non-archived threads without reading rollout history."""
    required = set(
        UNION_REQUIRED_COLUMNS if required_columns is None else required_columns
    )
    connection = open_database(state_db)
    try:
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(threads)").fetchall()
        }
        missing = required - columns
        if missing:
            raise CskitDataError(
                "当前 Codex threads 表缺少必要字段：" + ", ".join(sorted(missing))
            )

        # Optional columns differ across Codex versions; degrade instead of failing.
        name_expression = "name" if "name" in columns else "NULL"
        preview_expression = "preview" if "preview" in columns else "NULL"
        created_expression = (
            "COALESCE(NULLIF(created_at_ms, 0), created_at * 1000)"
            if "created_at_ms" in columns
            else "created_at * 1000" if "created_at" in columns
            else "0"
        )
        updated_expression = (
            "updated_at_ms" if "updated_at_ms" in columns
            else "updated_at * 1000" if "updated_at" in columns
            else "0"
        )
        recency_expression = (
            "recency_at_ms" if "recency_at_ms" in columns else updated_expression
        )
        # Columns only clonecode required: select NULL when a caller passed a
        # narrower required_columns and the schema lacks them.
        selected_optional = ", ".join(
            f"{name}" if name in columns else f"NULL AS {name}"
            for name in ("cwd", "model_provider", "model", "history_mode")
        )
        query = f"""
            SELECT
                id, rollout_path,
                {name_expression} AS db_name,
                title AS db_title,
                {preview_expression} AS db_preview,
                {selected_optional},
                {created_expression} AS created_ms,
                {updated_expression} AS updated_ms,
                {recency_expression} AS recency_ms
            FROM threads
            WHERE archived = 0 AND thread_source = 'user'
            ORDER BY recency_ms DESC, updated_ms DESC
        """
        try:
            rows = connection.execute(query).fetchall()
        except sqlite3.Error as exc:
            raise CskitDataError(f"读取会话列表失败：{exc}") from exc
    finally:
        connection.close()

    ui_titles = session_titles or {}
    ui_projects = project_names or {}
    project_counts: dict[str, int] = {}
    threads: list[ThreadRecord] = []
    for row in rows:
        thread_id = str(row["id"])
        db_name = str(row["db_name"] or "").strip()
        # Automated top-level tasks can be thread_source='user' yet never enter
        # the desktop index; a current DB name also keeps a freshly-created task
        # visible before its index entry is flushed.
        if sidebar_only and thread_id not in ui_titles and not db_name:
            continue
        display_name = str(
            ui_titles.get(thread_id)
            or db_name
            or row["db_title"]
            or row["db_preview"]
            or "未命名对话"
        ).strip() or "未命名对话"
        full_name = (
            db_name or str(ui_titles.get(thread_id) or "").strip() or display_name
        )
        project_name = ui_projects.get(thread_id, "独立任务")
        if max_per_project is not None:
            count = project_counts.get(project_name, 0)
            if count >= max_per_project:
                continue
            project_counts[project_name] = count + 1
        threads.append(
            ThreadRecord(
                id=thread_id,
                display_name=display_name,
                full_name=full_name,
                rollout_path=Path(str(row["rollout_path"] or "")),
                project_name=project_name,
                created_at_ms=int(row["created_ms"] or 0),
                updated_at_ms=int(row["updated_ms"] or 0),
                cwd=str(row["cwd"] or ""),
                model_provider=str(row["model_provider"] or ""),
                model=str(row["model"] or ""),
                history_mode=str(row["history_mode"] or ""),
                row=dict(row),
            )
        )
    return threads


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
