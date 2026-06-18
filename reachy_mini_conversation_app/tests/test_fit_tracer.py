"""Tests for TRACER fit script (Phase B'')."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from fit_tracer import (  # noqa: E402
    load_trace_texts,
    read_embedder_txt,
    write_embedder_txt,
)
from tracer_report_fr import generate_html_report_fr  # noqa: E402

pytest.importorskip("tracer")


def test_load_trace_texts(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"input": "Bonjour.", "teacher": "chat"}),
                json.dumps({"input": "Danse.", "teacher": "dance"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert load_trace_texts(path) == ["Bonjour.", "Danse."]


def test_load_trace_texts_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Trace file not found"):
        load_trace_texts(tmp_path / "missing.jsonl")


def test_embedder_txt_roundtrip(tmp_path: Path) -> None:
    artifact = tmp_path / ".tracer"
    model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    write_embedder_txt(artifact, model)
    assert read_embedder_txt(artifact) == model


def test_cmd_fit_calls_tracer_fit(tmp_path: Path) -> None:
    traces = tmp_path / "traces_all.jsonl"
    traces.write_text(
        json.dumps({"input": "Regarde-moi.", "teacher": "head_tracking:on"}) + "\n",
        encoding="utf-8",
    )
    artifact = tmp_path / ".tracer"
    emb_path = tmp_path / "traces_all_embeddings.npy"

    fake_manifest = MagicMock()
    fake_manifest.n_traces = 1
    fake_manifest.label_space = ["head_tracking:on"]
    fake_manifest.selected_method = "logreg"
    fake_manifest.target_teacher_agreement = 0.95
    fake_manifest.coverage_cal = 0.5
    fake_manifest.teacher_agreement_cal = 0.99
    fake_manifest.embedding_dim = 4

    fake_result = MagicMock()
    fake_result.manifest = fake_manifest
    fake_result.notes = ["ok"]

    import fit_tracer as ft

    with (
        patch("tracer.Embedder.from_sentence_transformers") as mock_st,
        patch("tracer.fit", return_value=fake_result) as mock_fit,
    ):
        mock_st.return_value.embed.return_value = np.zeros((1, 4), dtype=np.float32)
        rc = ft.cmd_fit(
            traces,
            artifact,
            "sentence-transformers/test-model",
            embeddings_path=emb_path,
        )

    assert rc == 0
    mock_fit.assert_called_once()
    _, kwargs = mock_fit.call_args
    assert kwargs["embeddings"].shape == (1, 4)
    assert read_embedder_txt(artifact) == "sentence-transformers/test-model"
    assert emb_path.exists()


def test_french_report_contains_context(tmp_path: Path) -> None:
    artifact = tmp_path / ".tracer"
    artifact.mkdir()
    (artifact / "manifest.json").write_text(
        json.dumps(
            {
                "n_traces": 10,
                "label_space": ["chat", "dance"],
                "selected_method": "l2d",
                "coverage_cal": 0.5,
                "teacher_agreement_cal": 0.96,
                "embedding_dim": 384,
                "target_teacher_agreement": 0.95,
            }
        ),
        encoding="utf-8",
    )
    (artifact / "qualitative_report.json").write_text(
        json.dumps({"slices": [], "boundary_pairs": [], "handled_examples": [], "deferred_examples": []}),
        encoding="utf-8",
    )
    (artifact / "embedder.txt").write_text("test-model\n", encoding="utf-8")
    out = artifact / "report.html"
    generate_html_report_fr(artifact, output_path=out, project_root=tmp_path)
    html = out.read_text(encoding="utf-8")
    assert 'lang="fr"' in html
    assert "Phase C" in html
    assert "Couverture" in html
    assert "Parité teacher" in html
