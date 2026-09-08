from __future__ import annotations

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
