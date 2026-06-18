"""Tests for shadow-mode trace collection."""

from __future__ import annotations
import json
from pathlib import Path

import pytest

from reachy_mini_conversation_app.trace_collector import TraceCollector, make_label


def _read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize(
    ("tool_name", "args", "expected"),
    [
        ("head_tracking", {"start": True}, "head_tracking:on"),
        ("head_tracking", {"start": False}, "head_tracking:off"),
        ("play_emotion", {"emotion": "sad"}, "play_emotion:sad"),
        ("dance", {}, "dance"),
        ("dance", {"move": "side_to_side_sway"}, "dance:side_to_side_sway"),
        ("move_head", {"direction": "left"}, "move_head:left"),
        ("move_head", {"direction": "right"}, "move_head:right"),
        ("move_head", {"direction": "up"}, "move_head:up"),
        ("move_head", {"direction": "down"}, "move_head:down"),
        ("move_head", {"direction": "front"}, "move_head:front"),
        ("stop_dance", {"dummy": True}, "stop"),
        ("stop_emotion", {"dummy": True}, "stop"),
        ("camera", {"question": "what do you see?"}, "chat"),
        ("idle_do_nothing", {"reason": "idle"}, "chat"),
    ],
)
def test_make_label(tool_name: str, args: dict[str, object], expected: str) -> None:
    """Map each tool schema to the expected TRACER label."""
    assert make_label(tool_name, args) == expected


def test_transcript_tool_done_writes_composite_label(tmp_path: Path) -> None:
    """A transcript followed by a tool call should flush a composite label."""
    log_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(str(log_path))

    collector.on_user_transcript("regarde moi")
    collector.on_tool_call("head_tracking", '{"start": true}')
    collector.on_response_done()

    records = _read_lines(log_path)
    assert len(records) == 1
    assert records[0]["input"] == "regarde moi"
    assert records[0]["teacher"] == "head_tracking:on"
    assert records[0]["n_tools"] == 1
    assert records[0]["tool_raw"] == "head_tracking"
    assert records[0]["args_raw"] == '{"start": true}'


def test_transcript_done_without_tool_is_chat(tmp_path: Path) -> None:
    """A transcript with no tool call should be labeled chat."""
    log_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(str(log_path))

    collector.on_user_transcript("raconte moi ta journée")
    collector.on_response_done()

    records = _read_lines(log_path)
    assert len(records) == 1
    assert records[0]["teacher"] == "chat"
    assert records[0]["n_tools"] == 0
    assert records[0]["tool_raw"] is None
    assert records[0]["args_raw"] is None


def test_second_transcript_flushes_previous_turn(tmp_path: Path) -> None:
    """A new transcript should flush the previous pending turn defensively."""
    log_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(str(log_path))

    collector.on_user_transcript("premier tour")
    collector.on_user_transcript("deuxième tour")
    collector.on_response_done()

    records = _read_lines(log_path)
    assert len(records) == 2
    assert records[0]["input"] == "premier tour"
    assert records[0]["teacher"] == "chat"
    assert records[1]["input"] == "deuxième tour"
    assert records[1]["teacher"] == "chat"


def test_tool_without_transcript_is_ignored(tmp_path: Path) -> None:
    """Idle-policy tool calls without a user transcript should not be recorded."""
    log_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(str(log_path))

    collector.on_tool_call("dance", "{}")
    collector.on_response_done()

    assert not log_path.exists()


def test_camera_keeps_chat_label_with_tool_audit_fields(tmp_path: Path) -> None:
    """Camera tool calls should keep teacher=chat while preserving audit fields."""
    log_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(str(log_path))

    collector.on_user_transcript("décris ce que tu vois")
    collector.on_tool_call("camera", '{"question": "what is in view?"}')
    collector.on_response_done()

    records = _read_lines(log_path)
    assert records[0]["teacher"] == "chat"
    assert records[0]["tool_raw"] == "camera"
    assert records[0]["n_tools"] == 1


def test_only_first_tool_defines_label(tmp_path: Path) -> None:
    """Only the first tool call of a turn should define the teacher label."""
    log_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(str(log_path))

    collector.on_user_transcript("regarde à gauche puis à droite")
    collector.on_tool_call("move_head", '{"direction": "left"}')
    collector.on_tool_call("move_head", '{"direction": "right"}')
    collector.on_response_done()

    records = _read_lines(log_path)
    assert records[0]["teacher"] == "move_head:left"
    assert records[0]["n_tools"] == 2


def test_speech_started_flushes_stale_turn(tmp_path: Path) -> None:
    """Speech started should flush any stale pending turn."""
    log_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(str(log_path))

    collector.on_user_transcript("tour abandonné")
    collector.on_speech_started()

    records = _read_lines(log_path)
    assert len(records) == 1
    assert records[0]["teacher"] == "chat"


def test_gate_bypass_flushes_with_tracer_metadata(tmp_path: Path) -> None:
    """A TRACER bypass should flush immediately with routed_by metadata."""
    log_path = tmp_path / "traces.jsonl"
    collector = TraceCollector(str(log_path))

    collector.on_user_transcript("regarde-moi")
    collector.on_gate_bypass(
        label="head_tracking:on",
        accept_score=0.95,
        tool_raw="head_tracking",
        args_raw='{"start": true}',
    )

    records = _read_lines(log_path)
    assert len(records) == 1
    assert records[0]["teacher"] == "head_tracking:on"
    assert records[0]["routed_by"] == "tracer"
    assert records[0]["accept_score"] == 0.95
    assert records[0]["tool_raw"] == "head_tracking"
