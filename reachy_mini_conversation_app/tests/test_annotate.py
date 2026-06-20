"""Tests for the TRACER annotation tool (scripts/annotate.py)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import annotate  # noqa: E402


def _write_traces(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _session(traces_path: Path, session_path: Path, rows: list[dict]) -> annotate.AnnotationSession:
    _write_traces(traces_path, rows)
    taxonomy = annotate.LabelTaxonomy(rows)
    return annotate.AnnotationSession(traces_path, session_path, taxonomy)


def test_validate_keeps_line(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    session_file = tmp_path / ".annotation_session.jsonl"
    rows = [
        {"input": "Bonjour.", "teacher": "chat", "ts": "2026-06-18T12:00:10Z", "n_tools": 0},
        {"input": "Danse.", "teacher": "dance", "ts": "2026-06-18T12:00:11Z", "n_tools": 1},
    ]
    session = _session(traces, session_file, rows)
    session.annotate(0, "validate")

    output, counts = session.apply_decisions()
    assert counts["validate"] == 1
    assert counts["unchanged"] == 1
    assert output[0] == rows[0]
    assert output[1] == rows[1]


def test_correct_updates_teacher_and_audit_fields(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    session_file = tmp_path / ".annotation_session.jsonl"
    rows = [
        {
            "input": "Regarde-moi.",
            "teacher": "move_head:front",
            "ts": "2026-06-18T12:01:40Z",
            "n_tools": 1,
            "tool_raw": "move_head",
            "args_raw": '{"direction": "front"}',
        },
    ]
    session = _session(traces, session_file, rows)
    session.annotate(0, "correct", teacher="head_tracking:on")

    output, counts = session.apply_decisions()
    assert counts["correct"] == 1
    assert output[0]["teacher"] == "head_tracking:on"
    assert output[0]["tool_raw"] == "head_tracking"
    assert output[0]["args_raw"] == '{"start": true}'
    assert output[0]["n_tools"] == 1
    assert output[0]["source_teacher"] == "move_head:front"


def test_correct_sets_also_chat(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    session_file = tmp_path / ".annotation_session.jsonl"
    rows = [
        {"input": "J'ai marron.", "teacher": "chat", "ts": "2026-06-18T12:23:22Z", "n_tools": 0},
    ]
    session = _session(traces, session_file, rows)
    session.annotate(0, "correct", teacher="play_emotion:irritated", also_chat=True)

    output, _ = session.apply_decisions()
    assert output[0]["teacher"] == "play_emotion:irritated"
    assert output[0]["also_chat"] is True
    assert output[0]["source_teacher"] == "chat"


def test_delete_removes_line(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    session_file = tmp_path / ".annotation_session.jsonl"
    rows = [
        {"input": "Bonjour.", "teacher": "chat", "ts": "2026-06-18T12:00:10Z"},
        {"input": "Hmm.", "teacher": "chat", "ts": "2026-06-18T12:00:11Z"},
    ]
    session = _session(traces, session_file, rows)
    session.annotate(1, "delete")

    output, counts = session.apply_decisions()
    assert counts["delete"] == 1
    assert len(output) == 1
    assert output[0]["input"] == "Bonjour."


def test_finalize_creates_backup(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    session_file = tmp_path / ".annotation_session.jsonl"
    rows = [
        {"input": "Bonjour.", "teacher": "chat", "ts": "2026-06-18T12:00:10Z"},
    ]
    session = _session(traces, session_file, rows)
    session.annotate(0, "validate")
    original = traces.read_text(encoding="utf-8")

    result = session.finalize()
    assert result["ok"] is True
    assert Path(result["backup"]).exists()
    assert traces.read_text(encoding="utf-8") == original
    assert not session_file.exists()


def test_invalid_teacher_blocks_finalize(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    session_file = tmp_path / ".annotation_session.jsonl"
    rows = [{"input": "Test.", "teacher": "chat", "ts": "2026-06-18T12:00:10Z"}]
    session = _session(traces, session_file, rows)
    session.log.append(
        {
            "line_id": 0,
            "action": "correct",
            "teacher": "not_a_real_label",
            "at": "2026-06-20T10:00:00Z",
        }
    )

    original = traces.read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="label invalide"):
        session.finalize()
    assert traces.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob("traces.jsonl.bak-*")) == []


def test_session_resume(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    session_file = tmp_path / ".annotation_session.jsonl"
    rows = [
        {"input": "A", "teacher": "chat", "ts": "1"},
        {"input": "B", "teacher": "dance", "ts": "2"},
        {"input": "C", "teacher": "stop", "ts": "3"},
    ]
    session = _session(traces, session_file, rows)
    session.annotate(0, "validate")
    session.annotate(1, "delete")

    resumed = _session(traces, session_file, rows)
    assert resumed.decisions[0]["action"] == "validate"
    assert resumed.decisions[1]["action"] == "delete"
    assert resumed.queue(limit=10) == [resumed._queue_item(2, rows[2])]


def test_top4_from_file_frequencies(tmp_path: Path) -> None:
    rows = [
        {"input": "a", "teacher": "chat"},
        {"input": "b", "teacher": "chat"},
        {"input": "c", "teacher": "dance"},
        {"input": "d", "teacher": "head_tracking:on"},
    ]
    taxonomy = annotate.LabelTaxonomy(rows)
    assert taxonomy.default_top4[0] == "chat"


def test_undo_restores_queue(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    session_file = tmp_path / ".annotation_session.jsonl"
    rows = [
        {"input": "A", "teacher": "chat", "ts": "1"},
        {"input": "B", "teacher": "dance", "ts": "2"},
    ]
    session = _session(traces, session_file, rows)
    session.annotate(0, "validate")
    session.undo()
    assert session.queue(limit=1)[0]["line_id"] == 0


def test_parse_emotion_intents() -> None:
    intents = annotate._parse_emotion_intents(annotate.PLAY_EMOTION_PATH)
    assert "happy" in intents
    assert "random" in intents


def test_is_valid_teacher_emotion() -> None:
    taxonomy = annotate.LabelTaxonomy([])
    assert taxonomy.is_valid_teacher("play_emotion:happy")
    assert not taxonomy.is_valid_teacher("play_emotion:random")
    assert not taxonomy.is_valid_teacher("play_emotion:unknown")
