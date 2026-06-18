"""Shadow-mode JSONL trace collection for TRACER intent-gate training."""

from __future__ import annotations
import json
import logging
from typing import Any
from pathlib import Path
from datetime import UTC, datetime
from dataclasses import dataclass


logger = logging.getLogger(__name__)

_NON_BYPASS_TOOLS = frozenset({"camera", "idle_do_nothing"})


def make_label(tool_name: str, args: dict[str, Any]) -> str:
    """Map a tool call to the TRACER label taxonomy (§4 of SPEC_TRACER_REACHY)."""
    if tool_name in _NON_BYPASS_TOOLS:
        return "chat"

    if tool_name == "head_tracking":
        start = args.get("start")
        if start is True:
            return "head_tracking:on"
        if start is False:
            return "head_tracking:off"
        return "chat"

    if tool_name == "play_emotion":
        emotion = args.get("emotion")
        if isinstance(emotion, str) and emotion:
            return f"play_emotion:{emotion}"
        return "chat"

    if tool_name == "dance":
        move = args.get("move")
        if isinstance(move, str) and move.strip():
            return f"dance:{move}"
        return "dance"

    if tool_name == "move_head":
        direction = args.get("direction")
        if isinstance(direction, str) and direction:
            return f"move_head:{direction}"
        return "chat"

    if tool_name in ("stop_dance", "stop_emotion"):
        return "stop"

    return "chat"


@dataclass
class _PendingTurn:
    input: str
    ts: str
    label: str | None = None
    n_tools: int = 0
    tool_raw: str | None = None
    args_raw: str | None = None


class TraceCollector:
    """Collect one JSONL trace per user turn (input → LLM tool decision)."""

    def __init__(self, log_path: str) -> None:
        """Initialize the collector; creates parent directories if needed."""
        self._log_path = Path(log_path)
        self._pending: _PendingTurn | None = None

    def on_user_transcript(self, transcript: str) -> None:
        """Record the user transcript for the current turn; flush any stale turn first."""
        text = transcript.strip()
        if not text:
            return
        self._flush_pending()
        self._pending = _PendingTurn(input=text, ts=_utc_now_iso())

    def on_tool_call(self, tool_name: str, args_json: str) -> None:
        """Record a tool call; the first call of the turn defines the teacher label."""
        if self._pending is None:
            return

        self._pending.n_tools += 1
        if self._pending.n_tools > 1:
            return

        self._pending.tool_raw = tool_name
        self._pending.args_raw = args_json
        try:
            args = json.loads(args_json)
        except json.JSONDecodeError:
            logger.warning("TraceCollector: invalid tool args JSON for %r", tool_name)
            args = {}
        if not isinstance(args, dict):
            args = {}
        self._pending.label = make_label(tool_name, args)

    def on_response_done(self) -> None:
        """Flush the current turn when the LLM response cycle completes."""
        self._flush_pending()

    def on_speech_started(self) -> None:
        """Defensively flush a stale turn when the user starts speaking again."""
        self._flush_pending()

    def on_gate_bypass(
        self,
        *,
        label: str,
        accept_score: float,
        tool_raw: str,
        args_raw: str,
        n_tools: int = 1,
    ) -> None:
        """Flush the current turn immediately after a TRACER bypass (no LLM response)."""
        pending = self._pending
        if pending is None:
            return
        self._pending = None
        record = {
            "input": pending.input,
            "teacher": label,
            "ts": pending.ts,
            "n_tools": n_tools,
            "tool_raw": tool_raw,
            "args_raw": args_raw,
            "routed_by": "tracer",
            "accept_score": accept_score,
        }
        self._append_record(record)

    def _flush_pending(self) -> None:
        pending = self._pending
        if pending is None:
            return
        self._pending = None

        if pending.n_tools == 0:
            teacher = "chat"
            tool_raw: str | None = None
            args_raw: str | None = None
        else:
            teacher = pending.label or "chat"
            tool_raw = pending.tool_raw
            args_raw = pending.args_raw

        record = {
            "input": pending.input,
            "teacher": teacher,
            "ts": pending.ts,
            "n_tools": pending.n_tools,
            "tool_raw": tool_raw,
            "args_raw": args_raw,
        }
        self._append_record(record)

    def _append_record(self, record: dict[str, Any]) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("TraceCollector: failed to append trace to %s", self._log_path)


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
