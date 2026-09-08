"""Sync Codex's `threads` table with the Provider that config.toml now selects.

After CC Switch rewrites `~/.codex/config.toml`, existing threads still carry the
previous provider/model, so the desktop app hides them. This subcommand is the
only part of cskit that writes: it updates every row's `model_provider`/`model`
to match the current top-level config.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from .errors import CskitConfigError


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
