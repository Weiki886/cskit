"""Read Codex rollout JSONL files and their paginated ancestors, read-only.

This module owns only the *traversal* layer: walking a rollout plus any
`history_base` ancestors in chronological order. Message extraction stays in
each subcommand, because `export` and `clone` intentionally keep different
semantics (attachments, fallback handling, dedup keys).

Every function here treats rollouts as strictly read-only.
"""

import json
import pathlib

from .errors import CskitRolloutError


class RolloutLineage:
    """Result of a lineage walk.

    `source_paths` and `warnings` are filled in as `events` is consumed, so read
    them after iterating.
    """

    def __init__(self, events, source_paths, warnings):
        self.events = events
        self.source_paths = source_paths
        self.warnings = warnings


def _iter_jsonl_prefix(path, byte_limit, warnings):
    """Yield JSON objects from a rollout prefix without loading the whole file."""
    path = pathlib.Path(path)
    if not path.is_file():
        raise CskitRolloutError(f"找不到 rollout 文件：{path}")
    if byte_limit is not None and byte_limit < 0:
        raise CskitRolloutError(f"history_base 的 byte offset 非法：{byte_limit}")
    file_size = path.stat().st_size
    if byte_limit is not None and byte_limit > file_size:
        raise CskitRolloutError(
            f"history_base 的 byte offset 超出父 rollout 大小：{path}"
        )

    with path.open("rb") as handle:
        remaining = byte_limit
        line_number = 0
        while remaining is None or remaining > 0:
            raw = handle.readline() if remaining is None else handle.readline(remaining)
            if not raw:
                break
            line_number += 1
            if remaining is not None:
                remaining -= len(raw)
                if not raw.endswith(b"\n"):
                    warnings.append(
                        f"父历史截断点不在 JSONL 行边界，已忽略残缺行：{path.name}"
                    )
                    break
            if not raw.strip():
                continue
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                warnings.append(f"忽略无法解析的 JSONL 行：{path.name}:{line_number}")
                continue
            if isinstance(value, dict):
                yield value


def _read_history_base(path, byte_limit):
    """Read only far enough to find the first session_meta and its history_base."""
    probe = []
    for event in _iter_jsonl_prefix(path, byte_limit, probe):
        if event.get("type") != "session_meta":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            return None
        candidate = payload.get("history_base")
        return candidate if isinstance(candidate, dict) else None
    return None


class HistoryResolver:
    """Resolve paginated rollout segments by the UUID suffix in their filenames."""

    def __init__(self, codex_home):
        self.codex_home = pathlib.Path(codex_home)
        self._paths = None

    def _all_rollouts(self):
        if self._paths is None:
            paths = []
            for folder_name in ("sessions", "archived_sessions"):
                folder = self.codex_home / folder_name
                if folder.is_dir():
                    paths.extend(folder.rglob("*.jsonl"))
            self._paths = paths
        return self._paths

    def resolve(self, segment_id, current_path):
        current = pathlib.Path(current_path).resolve()
        candidates = []
        for path in self._all_rollouts():
            name = path.name
            if name.endswith(f"_{segment_id}.jsonl"):
                priority = 0
            elif name.endswith(f"-{segment_id}.jsonl"):
                priority = 1
            elif segment_id in name:
                priority = 2
            else:
                continue
            if path.resolve() != current:
                candidates.append((priority, path))
        if not candidates:
            raise CskitRolloutError(
                f"找不到 history_base 指向的父 rollout：{segment_id}"
            )
        candidates.sort(key=lambda item: (item[0], item[1].name))
        return candidates[0][1]


def iter_rollout_events(path, resolver, byte_limit=None, warnings=None, stack=()):
    """Walk a rollout and its paginated ancestors, oldest event first.

    `stack` carries the resolved paths already being visited so a cyclic
    `history_base` chain is reported instead of recursing forever.
    """
    source_paths = []
    collected_warnings = warnings if warnings is not None else []

    def walk(current_path, current_limit, current_stack):
        resolved = pathlib.Path(current_path).resolve()
        if resolved in current_stack:
            raise CskitRolloutError(f"检测到循环 history_base：{current_path}")
        history_base = _read_history_base(current_path, current_limit)
        if history_base:
            parent_id = history_base.get("thread_id")
            parent_limit = history_base.get("end_byte_offset")
            if not isinstance(parent_id, str) or not isinstance(parent_limit, int):
                raise CskitRolloutError(f"history_base 字段不完整：{current_path}")
            parent_path = resolver.resolve(parent_id, current_path)
            for event in walk(parent_path, parent_limit, current_stack + (resolved,)):
                yield event
        for event in _iter_jsonl_prefix(current_path, current_limit, collected_warnings):
            yield event
        if resolved not in source_paths:
            source_paths.append(resolved)

    return RolloutLineage(
        walk(path, byte_limit, tuple(stack)), source_paths, collected_warnings
    )
