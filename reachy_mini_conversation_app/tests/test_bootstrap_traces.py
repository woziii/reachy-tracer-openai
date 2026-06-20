"""Tests for TRACER bootstrap scripts (Phase B')."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from bootstrap_catalog import CHAT_TRAPS, MIN_CHAT_TRAPS, MIN_PARAPHRASES_PER_LABEL, PARAPHRASES
from bootstrap_traces import compute_stats, generate_synthetic, merge_traces, validate_catalog
from tracer_dataset_utils import build_row, tool_fields

# reachy_mini_conversation_app.trace_collector
sys.path.insert(0, str(ROOT / "src"))
from reachy_mini_conversation_app.trace_collector import make_label


def _normalize(text: str) -> str:
    return text.strip()


def test_validate_catalog_minimums() -> None:
    validate_catalog()
    for teacher, phrases in PARAPHRASES.items():
        unique = {_normalize(p) for p in phrases}
        unique.discard("")
        assert len(unique) >= MIN_PARAPHRASES_PER_LABEL, teacher
    traps = {_normalize(p) for p in CHAT_TRAPS}
    traps.discard("")
    assert len(traps) >= MIN_CHAT_TRAPS


def test_generate_produces_valid_rows() -> None:
    rows = generate_synthetic(exclude_real=False)
    assert rows
    for row in rows[:50]:
        assert "input" in row and row["input"]
        assert "teacher" in row and row["teacher"]
        assert row.get("source") == "bootstrap"
        tool_raw, args_raw, n_tools = tool_fields(row["teacher"])
        assert row["tool_raw"] == tool_raw
        assert row["args_raw"] == args_raw
        assert row["n_tools"] == n_tools


def test_generate_no_duplicate_inputs() -> None:
    rows = generate_synthetic(exclude_real=False)
    seen: set[str] = set()
    for row in rows:
        assert row["input"] not in seen
        seen.add(row["input"])


def test_generate_excludes_real_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "traces.jsonl"
    real.write_text(
        json.dumps({"input": "Danse.", "teacher": "dance"}) + "\n",
        encoding="utf-8",
    )
    import bootstrap_traces as bt

    monkeypatch.setattr(bt, "REAL_PATH", real)
    rows = generate_synthetic(exclude_real=True)
    assert "Danse." not in {r["input"] for r in rows}


def test_chat_traps_and_command_priority() -> None:
    command_inputs: dict[str, str] = {}
    for teacher, phrases in PARAPHRASES.items():
        for phrase in phrases:
            key = _normalize(phrase)
            if key:
                command_inputs[key] = teacher

    rows = generate_synthetic(exclude_real=False)
    by_input = {r["input"]: r["teacher"] for r in rows}

    for phrase in CHAT_TRAPS:
        key = _normalize(phrase)
        if key not in by_input:
            continue
        if key in command_inputs:
            assert by_input[key] == command_inputs[key]
        else:
            assert by_input[key] == "chat"


def test_merge_real_wins_on_conflict(tmp_path: Path) -> None:
    real = tmp_path / "real.jsonl"
    synth = tmp_path / "synth.jsonl"
    out = tmp_path / "all.jsonl"
    real.write_text(
        json.dumps({"input": "Danse.", "teacher": "chat", "source": "real"}) + "\n",
        encoding="utf-8",
    )
    synth.write_text(
        json.dumps({"input": "Danse.", "teacher": "dance", "source": "bootstrap"}) + "\n",
        encoding="utf-8",
    )
    merged, stats = merge_traces(real_path=real, synth_path=synth, out_path=out)
    assert len(merged) == 1
    assert merged[0]["teacher"] == "chat"
    assert stats["conflicts"] == 1


def test_compute_stats_flags_small_classes() -> None:
    rows = [
        {"input": "a", "teacher": "chat"},
        {"input": "b", "teacher": "dance"},
        {"input": "c", "teacher": "dance"},
    ]
    stats = compute_stats(rows, min_threshold=10)
    assert stats["total"] == 3
    assert "dance" in stats["small_classes"]


@pytest.mark.parametrize(
    ("teacher", "tool_name", "args"),
    [
        ("head_tracking:on", "head_tracking", {"start": True}),
        ("head_tracking:off", "head_tracking", {"start": False}),
        ("dance", "dance", {}),
        ("stop", "stop_dance", {"dummy": True}),
        ("move_head:left", "move_head", {"direction": "left"}),
        ("play_emotion:sad", "play_emotion", {"emotion": "sad"}),
        ("chat", "camera", {}),
    ],
)
def test_tool_fields_match_make_label(teacher: str, tool_name: str, args: dict) -> None:
    if teacher == "chat":
        assert tool_fields(teacher) == (None, None, 0)
        assert make_label(tool_name, args) == "chat"
        return
    tool_raw, args_raw, n_tools = tool_fields(teacher)
    assert n_tools == 1
    assert tool_raw == tool_name
    parsed_args = json.loads(args_raw or "{}")
    assert make_label(tool_raw, parsed_args) == teacher


def test_build_row_optional_fields() -> None:
    row = build_row("Salut", "chat", source="bootstrap", also_chat=True)
    assert row["also_chat"] is True

    row2 = build_row("Boo", "play_emotion:surprised", also_head_tracking=True)
    assert row2["also_head_tracking"] is True
    assert row["source"] == "bootstrap"
