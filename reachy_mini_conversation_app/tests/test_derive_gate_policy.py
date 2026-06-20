"""Tests for gate policy derivation and preview helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import derive_gate_policy as dgp  # noqa: E402
from gate_policy_utils import (  # noqa: E402
    aggregate_annotation_flags,
    preview_phase2_runtime,
    suggest_policy_from_stats,
)


def test_preview_surprise_with_tracking() -> None:
    out = preview_phase2_runtime(
        "play_emotion:surprised",
        also_head_tracking=True,
        also_chat=False,
    )
    assert out["mode"] == "bypass"
    assert "head_tracking" in out["actions"][0]
    assert "play_emotion" in out["actions"][1]


def test_preview_irritated_hybrid() -> None:
    out = preview_phase2_runtime(
        "play_emotion:irritated",
        also_chat=True,
        also_head_tracking=False,
    )
    assert out["mode"] == "hybrid"
    assert "voix LLM" in out["summary"]


def test_preview_chat_defer() -> None:
    out = preview_phase2_runtime("chat")
    assert out["mode"] == "defer"


def test_aggregate_and_suggest_policy() -> None:
    rows = [
        {"teacher": "play_emotion:surprised", "also_head_tracking": True},
        {"teacher": "play_emotion:surprised", "also_head_tracking": True},
        {"teacher": "play_emotion:surprised", "also_head_tracking": False},
        {"teacher": "play_emotion:irritated", "also_chat": True},
        {"teacher": "play_emotion:irritated", "also_chat": True},
        {"teacher": "play_emotion:irritated", "also_chat": False},
    ]
    stats = aggregate_annotation_flags(rows)
    suggestion = suggest_policy_from_stats(stats, min_samples=3, min_ratio=0.6)
    assert "play_emotion:surprised" in suggestion["enrichment_candidates"]
    assert "play_emotion:irritated" in suggestion["hybrid_candidates"]


def test_derive_gate_policy_cli(tmp_path: Path) -> None:
    traces = tmp_path / "traces.jsonl"
    traces.write_text(
        json.dumps(
            {
                "input": "Boo!",
                "teacher": "play_emotion:surprised",
                "also_head_tracking": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    out_json = tmp_path / "report.json"
    rc = dgp.cmd_report(traces, min_samples=1, min_ratio=0.5, output_json=out_json)
    assert rc == 0
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["n_rows"] == 1
    assert "python_snippet" in report
