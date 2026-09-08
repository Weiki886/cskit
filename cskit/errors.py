"""Error hierarchy shared by every cskit subcommand."""


class CskitError(RuntimeError):
    """Base class for errors that can be shown directly to the CLI user."""


class CskitRolloutError(CskitError):
    """A rollout file is missing, unreadable, or has inconsistent pagination."""


class CskitConfigError(CskitError):
    """Codex configuration is missing or cannot be parsed."""


class CskitDataError(CskitError):
    """Codex SQLite state or sidebar state is missing or inconsistent."""
