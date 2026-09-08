"""Sync Codex's `threads` table with the Provider that config.toml now selects.

After CC Switch rewrites `~/.codex/config.toml`, existing threads still carry the
previous provider/model, so the desktop app hides them. This subcommand is the
only part of cskit that writes: it updates every row's `model_provider`/`model`
to match the current top-level config.
"""

from __future__ import annotations

import datetime
import os
import pathlib
import re
import shutil
import sqlite3
from dataclasses import dataclass

from .errors import CskitConfigError
from .toml_util import read_top_level_keys


@dataclass(frozen=True)
class FixState:
    """The provider/model to write, plus the files the write touches."""

    provider: str
    model: str
    config_path: pathlib.Path
    db_path: pathlib.Path


def verify_state(state: FixState) -> None:
    """Reject a state that would write an empty provider or model."""
    if not state.provider:
        raise CskitConfigError(
            f"无法从 {state.config_path} 顶层读取 model_provider"
        )
    if not state.model:
        raise CskitConfigError(f"无法从 {state.config_path} 顶层读取 model")
    return None


def _provider_section_present(text: str, provider: str) -> bool:
    """Whether `[model_providers.<provider>]` is declared, bare or quoted.

    Codex writes the bare form, but a provider whose name contains a dot or dash
    is legally quoted in TOML, so both spellings must count as present.
    """
    pattern = re.compile(
        r"^\s*\[\s*model_providers\s*\.\s*(?:%s|\"%s\")\s*\]\s*$"
        % (re.escape(provider), re.escape(provider)),
        re.MULTILINE,
    )
    return pattern.search(text) is not None


def load_fix_state(config_path, db_path) -> FixState:
    """Read the provider/model that config.toml currently selects.

    Parsing is scope-aware: keys below a `[table]` header belong to that table,
    so a `model` inside `[model_providers.foo]` can never be mistaken for the
    top-level value.

    A missing `[model_providers.<provider>]` section is an error rather than
    something to synthesise: the section needs credentials that cskit cannot
    invent, and appending an incomplete one would produce a config that looks
    fixed but cannot authenticate.
    """
    config_path = pathlib.Path(config_path).expanduser()
    keys = read_top_level_keys(config_path, ("model", "model_provider"))
    state = FixState(
        provider=keys.get("model_provider", ""),
        model=keys.get("model", ""),
        config_path=config_path,
        db_path=pathlib.Path(db_path).expanduser(),
    )
    verify_state(state)

    text = config_path.read_text(encoding="utf-8")
    if not _provider_section_present(text, state.provider):
        raise CskitConfigError(
            f"{config_path} 缺少 [model_providers.{state.provider}] 段。\n"
            "  该段包含 base_url 与凭据，cskit 无法凭空生成；\n"
            "  请在 CC Switch 中重新切换一次该 Provider，让它写入完整配置。"
        )
    return state


def _enclosing_git_worktree(path: pathlib.Path):
    """The nearest ancestor containing `.git`, or None."""
    for candidate in (path,) + tuple(path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def backup_config(config_path, backup_dir) -> pathlib.Path:
    """Copy config.toml aside before writing, as an owner-only file.

    The copy inherits the original's secrets, so two things are enforced rather
    than assumed: the destination is an absolute path outside any git worktree
    (a token must not become stageable), and both directory and file are
    restricted to the owner.

    Each call writes a new timestamped name, so an earlier backup is never
    silently replaced by a later one.
    """
    config_path = pathlib.Path(config_path).expanduser()
    backup_dir = pathlib.Path(backup_dir).expanduser()

    if not backup_dir.is_absolute():
        raise CskitConfigError(
            f"备份目录必须是绝对路径，收到：{backup_dir}"
        )
    worktree = _enclosing_git_worktree(backup_dir)
    if worktree is not None:
        raise CskitConfigError(
            f"备份目录位于 git 仓库内（{worktree}），可能把凭据提交上去。\n"
            "  请改用仓库外的目录，例如 ~/.codex/.cskit-backups"
        )

    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backup_dir / f"config.toml.{stamp}.bak"
    shutil.copy2(config_path, destination)
    os.chmod(destination, 0o600)
    return destination


def sync_threads(db_path, provider, model) -> int:
    """Write the current provider/model into every thread row.

    Deliberately has no WHERE clause: after switching Provider, every thread
    needs the new value, matching what the shell version did.

    `BEGIN IMMEDIATE` takes the write lock up front. SQLite would already revert
    this single statement if it failed, so the transaction is not what makes the
    write atomic; it makes contention deterministic. The Codex desktop app writes
    to this database continuously, and a deferred transaction only discovers the
    conflict after starting to write, whereas IMMEDIATE fails before any row is
    touched and keeps the batch all-or-nothing if it ever grows past one
    statement.
    """
    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        conn.execute("BEGIN IMMEDIATE")
        cursor = conn.execute(
            "UPDATE threads SET model_provider = ?, model = ?",
            (provider, model),
        )
        affected = cursor.rowcount
        conn.commit()
        return affected
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def format_preview(state: FixState, thread_count: int, *, dry_run: bool) -> str:
    """Describe the write in terms of the two values it sets.

    Only the provider name, model name and row count are ever printed. The rest
    of config.toml — including `experimental_bearer_token` — is never echoed,
    because this output lands in terminal scrollback, CI logs and pasted-in AI
    prompts, and a leaked token cannot be un-leaked.
    """
    lines = [
        f"Provider：{state.provider}",
        f"模型：{state.model}",
        f"影响会话：{thread_count} 条（threads 表全部行）",
        f"配置来源：{state.config_path}",
        f"数据库：{state.db_path}",
    ]
    if dry_run:
        lines.append("")
        lines.append("✓ 预览完成：未写入任何数据")
    else:
        lines.append("")
        lines.append(f"✓ 已同步 {thread_count} 条会话到 {state.provider} / {state.model}")
    return "\n".join(lines)
