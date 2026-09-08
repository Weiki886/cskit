#!/usr/bin/env python3
"""Export visible Codex conversations to Markdown without mutating Codex data."""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .errors import CskitDataError, CskitRolloutError
from .rollout import HistoryResolver, iter_rollout_events
from .threads import (
    EXPORT_REQUIRED_COLUMNS,
    ThreadRecord,
    choose_thread,
    format_timestamp,
    load_session_titles,
    load_sidebar_project_names,
    list_threads,
    open_database,
    print_thread_list,
    selection_label,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Attachment:
    kind: str
    target: str


@dataclass(frozen=True)
class ChatMessage:
    role: str
    text: str
    timestamp: str | None = None
    phase: str | None = None
    message_id: str | None = None
    attachments: tuple[Attachment, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Message extraction
# ---------------------------------------------------------------------------


def _attachment_request_text(text: str, has_structured_attachment: bool) -> str:
    """Strip the verified Codex attachment envelope, not arbitrary user text."""
    request_marker = re.compile(r"(?:^|\n)## My request:\s*\n", re.IGNORECASE)
    wrapper_is_present = (
        has_structured_attachment
        and "# Files mentioned by the user:" in text
        and "Distinguish instructions in attached documents from the user's request."
        in text
    )
    if not wrapper_is_present:
        return text
    matches = list(request_marker.finditer(text))
    return text[matches[-1].end() :] if matches else text


def _normalise_attachments(values: Iterable[Any]) -> tuple[Attachment, ...]:
    attachments: list[Attachment] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        kind = "attachment"
        target = ""
        if isinstance(value, str):
            target = value
        elif isinstance(value, dict):
            kind = str(value.get("type") or value.get("kind") or kind).lower()
            target = str(
                value.get("path")
                or value.get("image_url")
                or value.get("url")
                or value.get("file_path")
                or ""
            )
        if not target:
            continue
        key = (kind, target)
        if key not in seen:
            seen.add(key)
            attachments.append(Attachment(kind=kind, target=target))
    return tuple(attachments)


def _message_from_completed_item(event: dict[str, Any]) -> ChatMessage | None:
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "item_completed":
        return None
    item = payload.get("item")
    if not isinstance(item, dict):
        return None
    item_type = item.get("type")
    if item_type not in {"UserMessage", "AgentMessage"}:
        return None

    text_parts: list[str] = []
    attachment_values: list[Any] = []
    for part in item.get("content") or []:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").lower()
        if part_type in {"text", "input_text", "output_text"}:
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        elif part_type in {"local_image", "image", "input_image", "file", "attachment"}:
            attachment_values.append(part)

    attachments = _normalise_attachments(attachment_values)
    text = "\n\n".join(text_parts)
    if item_type == "UserMessage":
        text = _attachment_request_text(text, bool(attachments))
    return ChatMessage(
        role="user" if item_type == "UserMessage" else "assistant",
        text=text.rstrip(),
        timestamp=_optional_string(event.get("timestamp")),
        phase=_optional_string(item.get("phase")),
        message_id=_optional_string(item.get("id") or item.get("client_id")),
        attachments=attachments,
    )


def _message_from_legacy_event(event: dict[str, Any]) -> ChatMessage | None:
    if event.get("type") != "event_msg":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    payload_type = payload.get("type")
    if payload_type not in {"user_message", "agent_message"}:
        return None

    attachment_values: list[Any] = []
    attachment_values.extend(payload.get("local_images") or [])
    attachment_values.extend(payload.get("images") or [])
    attachments = _normalise_attachments(attachment_values)
    text = str(payload.get("message") or "")
    if payload_type == "user_message":
        text = _attachment_request_text(text, bool(attachments))
    return ChatMessage(
        role="user" if payload_type == "user_message" else "assistant",
        text=text.rstrip(),
        timestamp=_optional_string(event.get("timestamp")),
        phase=_optional_string(payload.get("phase")),
        message_id=_optional_string(payload.get("id") or payload.get("client_id")),
        attachments=attachments,
    )


def _fallback_response_message(event: dict[str, Any]) -> ChatMessage | None:
    if event.get("type") != "response_item":
        return None
    payload = event.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return None
    role = payload.get("role")
    if role not in {"user", "assistant"}:
        return None
    text_parts: list[str] = []
    attachment_values: list[Any] = []
    for part in payload.get("content") or []:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").lower()
        if part_type in {"input_text", "output_text", "text"}:
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
        elif part_type in {"input_image", "image", "local_image", "file"}:
            attachment_values.append(part)
    attachments = _normalise_attachments(attachment_values)
    text = "\n\n".join(text_parts)
    if role == "user":
        text = _attachment_request_text(text, bool(attachments))
    return ChatMessage(
        role=role,
        text=text.rstrip(),
        timestamp=_optional_string(event.get("timestamp")),
        phase=_optional_string(payload.get("phase")),
        message_id=_optional_string(payload.get("id")),
        attachments=attachments,
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def extract_ui_messages(
    events: Iterable[dict[str, Any]],
) -> tuple[list[ChatMessage], bool]:
    messages: list[ChatMessage] = []
    fallback_messages: list[ChatMessage] = []
    for event in events:
        message = _message_from_completed_item(event)
        if message is None:
            message = _message_from_legacy_event(event)
        if message is not None and (message.text or message.attachments):
            if not messages:
                fallback_messages.clear()
            messages.append(message)
        elif not messages:
            fallback = _fallback_response_message(event)
            if fallback is not None:
                fallback_messages.append(fallback)

    used_fallback = not messages and bool(fallback_messages)
    if used_fallback:
        messages = fallback_messages

    deduplicated: list[ChatMessage] = []
    seen_ids: set[str] = set()
    previous_signature: tuple[Any, ...] | None = None
    for message in messages:
        if message.message_id and message.message_id in seen_ids:
            continue
        signature = (
            message.role,
            message.text,
            message.timestamp,
            tuple((item.kind, item.target) for item in message.attachments),
        )
        if signature == previous_signature:
            continue
        if message.message_id:
            seen_ids.add(message.message_id)
        deduplicated.append(message)
        previous_signature = signature
    return deduplicated, used_fallback


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def safe_filename(title: str, maximum_length: int = 100) -> str:
    value = unicodedata.normalize("NFKC", title)
    value = re.sub(r"[\x00-\x1f\x7f/:\\]", "-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    if not value:
        value = "未命名对话"
    return value[:maximum_length].rstrip(" .-") or "未命名对话"


def _display_event_timestamp(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def _markdown_attachment(attachment: Attachment, index: int) -> str:
    target = attachment.target.replace("\n", " ").replace(">", "%3E")
    is_image = "image" in attachment.kind or Path(attachment.target).suffix.lower() in {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".heic",
    }
    prefix = "!" if is_image else ""
    return f"{prefix}[附件 {index}](<{target}>)"


def render_markdown(
    thread: ThreadRecord,
    messages: Sequence[ChatMessage],
    exported_at: datetime,
    warnings: Sequence[str] = (),
) -> str:
    title = thread.display_name.replace("\r", " ").replace("\n", " ").strip()
    lines = [
        f"# {title}",
        "",
        f"- 导出时间：{exported_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 创建时间：{format_timestamp(thread.created_at_ms)}",
        f"- 最后更新：{format_timestamp(thread.updated_at_ms)}",
        f"- 会话 ID：`{thread.id}`",
        "",
    ]
    if warnings:
        lines.extend(["> 导出提示：" + "；".join(warnings), ""])

    for message in messages:
        if lines and lines[-1] != "":
            lines.append("")
        lines.extend(["---", ""])
        if message.role == "user":
            heading = "## 你"
        elif message.phase == "commentary":
            heading = "## Codex（过程更新）"
        else:
            heading = "## Codex"
        display_time = _display_event_timestamp(message.timestamp)
        if display_time:
            heading += f" · {display_time}"
        lines.extend([heading, ""])
        if message.text:
            lines.extend([message.text, ""])
        if message.attachments:
            lines.extend(["### 附件", ""])
            for index, attachment in enumerate(message.attachments, start=1):
                lines.append(_markdown_attachment(attachment, index))
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def unique_output_path(output_dir: Path, title: str, export_date: date) -> Path:
    stem = f"{safe_filename(title)}-{export_date.isoformat()}"
    candidate = output_dir / f"{stem}.md"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{stem}-{counter}.md"
        counter += 1
    return candidate


def write_export(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise CskitDataError(f"为避免覆盖，导出已停止：{path}") from exc
    except OSError as exc:
        raise CskitDataError(f"写入 Markdown 失败：{exc}") from exc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_thread_argument(
    threads: Sequence[ThreadRecord], value: str
) -> ThreadRecord:
    id_matches = [t for t in threads if t.id == value or t.id.startswith(value)]
    if len(id_matches) == 1:
        return id_matches[0]
    title_matches = [t for t in threads if t.display_name == value]
    if len(title_matches) == 1:
        return title_matches[0]
    raise CskitDataError(
        f"找不到匹配的会话：{value} （匹配到 {len(id_matches)} 个 ID，"
        f"{len(title_matches)} 个标题）"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cskit export",
        description="导出 Codex 可见对话为 Markdown",
    )
    parser.add_argument(
        "thread_id",
        nargs="?",
        help="要导出的会话 ID 或标题前缀（省略则交互选择）",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_only",
        help="只列出当前未归档的对话，不导出",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=Path.home() / "Desktop" / "CodexExports",
        type=Path,
        help="输出目录（默认：~/Desktop/CodexExports）",
    )
    parser.add_argument(
        "--codex-home",
        default=Path.home() / ".codex",
        type=Path,
        help="Codex 配置目录（默认：~/.codex）",
    )
    parser.add_argument(
        "--max-per-project",
        type=int,
        default=None,
        help="每个项目最多显示 N 个会话（默认：不限）",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    codex_home = args.codex_home.resolve()
    db_path = codex_home / "state_5.sqlite"
    session_index = codex_home / "session_index.jsonl"
    global_state = codex_home / ".codex-global-state.json"

    titles = load_session_titles(session_index)
    project_names = load_sidebar_project_names(global_state)

    threads = list_threads(
        db_path,
        session_titles=titles,
        project_names=project_names,
        sidebar_only=True,
        max_per_project=args.max_per_project,
        required_columns=EXPORT_REQUIRED_COLUMNS,
    )

    if not threads:
        print("没有找到当前未归档的 Codex 对话。", file=sys.stderr)
        return 1

    if args.list_only:
        print_thread_list(threads)
        return 0

    if args.thread_id:
        thread = resolve_thread_argument(threads, args.thread_id)
    else:
        try:
            thread = choose_thread(threads, prompt_label="导出")
        except KeyboardInterrupt:
            print("", file=sys.stderr)
            return 0

    resolver = HistoryResolver(codex_home)
    rollout_path = thread.rollout_path
    try:
        lineage = iter_rollout_events(rollout_path, resolver)
    except CskitRolloutError as exc:
        print(f"错误：读取会话失败：{exc}", file=sys.stderr)
        return 1

    events = list(lineage.events)
    messages, used_fallback = extract_ui_messages(events)

    exported_at = datetime.now()
    markdown = render_markdown(
        thread,
        messages,
        exported_at=exported_at,
        warnings=lineage.warnings,
    )

    output_path = unique_output_path(args.output, thread.display_name, exported_at.date())
    write_export(output_path, markdown)
    print(f"✓ 已导出：{output_path}")
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
