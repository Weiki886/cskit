"""Unified entry point: dispatch to the fix / export / clone subcommands.

Each subcommand keeps its own argument parser, so ``cskit export --help`` shows
exactly the options that subcommand accepts. Dispatch is lazy: importing cskit
does not import every subcommand, so a failure inside ``clone`` cannot break
``export``.
"""

from __future__ import annotations

import sys
from typing import Sequence

from . import __version__
from .errors import CskitError

USAGE = f"""cskit {__version__} — Codex / CC Switch 运维工具集

用法：
  cskit <命令> [选项]

命令：
  fix       切换 Provider 后同步 config.toml 与 threads 表的 provider/model
  export    将 Codex 可见对话只读导出为 Markdown
  clone     把旧会话的纯对话上下文克隆到当前 Provider 的新会话

其他：
  cskit --version        显示版本
  cskit <命令> --help    显示该命令的详细选项

示例：
  cskit export --list
  cskit clone --source 2BLOG --dry-run
"""

COMMANDS = ("fix", "export", "clone")


def _dispatch(name: str, argv: Sequence[str]) -> int | None:
    """Import the subcommand lazily and run it."""
    if name == "export":
        from .export import run
    elif name == "clone":
        from .clone import run
    elif name == "fix":
        from .fix import run
    else:  # pragma: no cover - guarded by the caller
        raise AssertionError(f"unknown command: {name}")
    return run(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in {"-h", "--help", "help"}:
        print(USAGE, end="")
        return 0
    if args[0] in {"-V", "--version", "version"}:
        print(f"cskit {__version__}")
        return 0

    command, rest = args[0], args[1:]
    if command not in COMMANDS:
        print(f"✗ 未知命令：{command}", file=sys.stderr)
        print(f"  可用命令：{', '.join(COMMANDS)}", file=sys.stderr)
        print("  运行 `cskit --help` 查看用法。", file=sys.stderr)
        return 2

    try:
        # Subcommands may return None to mean success; normalise here so the
        # process never exits with `None`.
        result = _dispatch(command, rest)
        return 0 if result is None else int(result)
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    except CskitError as exc:
        # Every user-facing failure funnels through CskitError, so the CLI can
        # show a clean message instead of a traceback.
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        # `cskit export --list | head` closes the pipe early; that is not an error.
        return 0


if __name__ == "__main__":
    sys.exit(main())
