"""Shared helpers for TRACER trace JSONL datasets (curate + bootstrap)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def tool_fields(teacher: str) -> tuple[str | None, str | None, int]:
    """Map a TRACER teacher label to trace_collector audit fields."""
    if teacher == "chat":
        return None, None, 0
    if teacher == "dance":
        return "dance", "{}", 1
    if teacher == "stop":
        return "stop_dance", '{"dummy": true}', 1
    if teacher.startswith("head_tracking:"):
        enabled = teacher.endswith(":on")
        return "head_tracking", json.dumps({"start": enabled}), 1
    if teacher.startswith("move_head:"):
        direction = teacher.split(":", 1)[1]
        return "move_head", json.dumps({"direction": direction}), 1
    if teacher.startswith("play_emotion:"):
        emotion = teacher.split(":", 1)[1]
        return "play_emotion", json.dumps({"emotion": emotion}), 1
    return None, None, 0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_row(
    inp: str,
    teacher: str,
    *,
    ts: str | None = None,
    source: str | None = None,
    also_chat: bool = False,
    source_teacher: str | None = None,
) -> dict[str, Any]:
    """Build one JSONL row compatible with trace_collector output."""
    tool_raw, args_raw, n_tools = tool_fields(teacher)
    row: dict[str, Any] = {
        "input": inp,
        "teacher": teacher,
        "ts": ts or utc_now_iso(),
        "n_tools": n_tools,
        "tool_raw": tool_raw,
        "args_raw": args_raw,
    }
    if also_chat:
        row["also_chat"] = True
    if source_teacher is not None:
        row["source_teacher"] = source_teacher
    if source is not None:
        row["source"] = source
    return row
