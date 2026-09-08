"""Sync Codex's `threads` table with the Provider that config.toml now selects.

After CC Switch rewrites `~/.codex/config.toml`, existing threads still carry the
previous provider/model, so the desktop app hides them. This subcommand is the
only part of cskit that writes: it updates every row's `model_provider`/`model`
to match the current top-level config.
"""

from __future__ import annotations

import pathlib
import re
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
