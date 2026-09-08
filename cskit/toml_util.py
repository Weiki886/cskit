"""Minimal top-level TOML key reader.

Codex config only needs a couple of scalar keys (`model`, `model_provider`) from
the document's top-level scope. `tomllib` would be ideal but is 3.11+, and this
project supports 3.9, so this reads just the top-level table.

Unlike a line-oriented `grep`/`awk` match, this stops at the first table header:
every key after `[section]` belongs to that table, not to the top level.
"""

import pathlib
import re

from .errors import CskitConfigError

_TABLE_HEADER = re.compile(r"^\s*\[")
_SCALAR_KEY = re.compile(
    r"""^\s*([A-Za-z0-9_-]+)\s*=\s*(['"])(.*?)\2\s*(?:\#.*)?$"""
)


def read_top_level_keys(path, wanted):
    """Return the requested keys found in the document's top-level table.

    Keys that are absent are omitted rather than defaulted, so callers can tell
    "missing" apart from "empty".
    """
    path = pathlib.Path(path).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CskitConfigError(f"找不到配置文件：{path}") from exc
    except OSError as exc:
        raise CskitConfigError(f"无法读取配置文件 {path}: {exc}") from exc
    except UnicodeError as exc:
        raise CskitConfigError(f"配置文件编码无法解析：{path}") from exc

    found = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if _TABLE_HEADER.match(line):
            # Everything below belongs to a table, so the top-level scope ends.
            break
        match = _SCALAR_KEY.match(line)
        if match is None:
            continue
        key = match.group(1)
        if key in wanted and key not in found:
            found[key] = match.group(3)
    return found
