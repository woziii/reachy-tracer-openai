#!/usr/bin/env python3
"""Fit TRACER routing policy on collected + synthetic traces (Phase B'')."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACES = ROOT / "tracer_data" / "traces_all.jsonl"
DEFAULT_ARTIFACT_DIR = ROOT / "tracer_data" / ".tracer"
DEFAULT_EMBEDDER = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEPS_HINT = "Install with: uv sync --extra intent_gate"


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value) if value else default


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def load_trace_texts(path: Path) -> list[str]:
    """Load user input texts from a TRACER JSONL trace file."""
    if not path.exists():
        raise FileNotFoundError(
            f"Trace file not found: {path}\n"
            "Run: python3 scripts/bootstrap_traces.py generate && merge"
        )
    texts: list[str] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if "input" not in row:
            raise ValueError(f"Missing 'input' at line {line_no} in {path}")
        texts.append(str(row["input"]))
    if not texts:
        raise ValueError(f"No traces found in {path}")
    return texts


def write_embedder_txt(artifact_dir: Path, embedder_name: str) -> Path:
    """Persist embedder model id for runtime consistency checks (Phase C)."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out = artifact_dir / "embedder.txt"
    out.write_text(embedder_name.strip() + "\n", encoding="utf-8")
    return out


def read_embedder_txt(artifact_dir: Path) -> str:
    return (artifact_dir / "embedder.txt").read_text(encoding="utf-8").strip()


def _import_tracer() -> Any:
    try:
        import tracer
    except ImportError as exc:
        raise SystemExit(f"tracer-llm is not installed. {DEPS_HINT}") from exc
    return tracer


def _import_embedder() -> Any:
    try:
        from tracer import Embedder
    except ImportError as exc:
        raise SystemExit(f"tracer-llm is not installed. {DEPS_HINT}") from exc
    return Embedder


def cmd_fit(
    traces_path: Path,
    artifact_dir: Path,
    embedder_name: str,
    *,
    target_ta: float = 0.95,
    batch_size: int = 64,
    embeddings_path: Path | None = None,
    reuse_embeddings: bool = False,
) -> int:
    tracer = _import_tracer()
    Embedder = _import_embedder()
    from tracer.config import FitConfig

    texts = load_trace_texts(traces_path)
    emb_out = embeddings_path or traces_path.with_name(f"{traces_path.stem}_embeddings.npy")

    import numpy as np

    if reuse_embeddings and emb_out.exists():
        print(f"Loading cached embeddings from {emb_out}")
        embeddings = np.load(emb_out)
        if len(embeddings) != len(texts):
            raise ValueError(
                f"Embedding/trace mismatch: {len(embeddings)} embeddings vs {len(texts)} traces"
            )
    else:
        print(f"Embedding {len(texts)} traces with {embedder_name} ...")
        embedder = Embedder.from_sentence_transformers(embedder_name, batch_size=batch_size)
        embeddings = embedder.embed(texts)
        np.save(emb_out, embeddings)
        print(f"Saved embeddings to {emb_out}")

    config = FitConfig(
        target_teacher_agreement=target_ta,
        verbose=True,
        skip_candidates=("gbt",),
    )
    print(f"Fitting TRACER (target TA={target_ta:.2f}) -> {artifact_dir}")
    result = tracer.fit(
        traces_path,
        artifact_dir,
        embeddings=embeddings,
        config=config,
    )
    write_embedder_txt(artifact_dir, embedder_name)

    manifest = result.manifest
    summary = {
        "artifact_dir": str(artifact_dir),
        "n_traces": manifest.n_traces,
        "n_labels": len(manifest.label_space),
        "label_space": manifest.label_space,
        "selected_method": manifest.selected_method,
        "target_teacher_agreement": manifest.target_teacher_agreement,
        "coverage_cal": manifest.coverage_cal,
        "teacher_agreement_cal": manifest.teacher_agreement_cal,
        "embedding_dim": manifest.embedding_dim,
        "notes": result.notes,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_report(artifact_dir: Path) -> int:
    tracer = _import_tracer()
    manifest = tracer.report(artifact_dir)
    print(
        json.dumps(
            {
                "version": manifest.version,
                "n_traces": manifest.n_traces,
                "label_space": manifest.label_space,
                "method": manifest.selected_method,
                "target_ta": manifest.target_teacher_agreement,
                "coverage": manifest.coverage_cal,
                "teacher_agreement": manifest.teacher_agreement_cal,
                "embedding_dim": manifest.embedding_dim,
                "n_retrains": manifest.n_retrains,
                "embedder": read_embedder_txt(artifact_dir)
                if (artifact_dir / "embedder.txt").exists()
                else None,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_report_html(artifact_dir: Path, output_path: Path | None, *, open_browser: bool) -> int:
    _import_tracer()
    import sys

    _scripts_dir = Path(__file__).resolve().parent
    if str(_scripts_dir) not in sys.path:
        sys.path.insert(0, str(_scripts_dir))
    from tracer_report_fr import generate_html_report_fr

    out = generate_html_report_fr(
        artifact_dir,
        output_path=output_path,
        project_root=ROOT,
    )
    print(f"Rapport HTML (FR) enregistré : {out}")
    if open_browser:
        import webbrowser

        webbrowser.open(f"file://{out.resolve()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit and analyze TRACER artifacts.")
    sub = parser.add_subparsers(dest="command", required=True)

    fit_p = sub.add_parser("fit", help="Embed traces and fit TRACER artifact")
    fit_p.add_argument("--traces", type=Path, default=_env_path("TRACE_ALL_PATH", DEFAULT_TRACES))
    fit_p.add_argument(
        "--artifact-dir",
        type=Path,
        default=_env_path("TRACER_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR),
    )
    fit_p.add_argument("--embedder", default=_env_str("TRACER_EMBEDDER", DEFAULT_EMBEDDER))
    fit_p.add_argument("--target-ta", type=float, default=0.95)
    fit_p.add_argument("--batch-size", type=int, default=64)
    fit_p.add_argument("--embeddings", type=Path, default=None)
    fit_p.add_argument("--reuse-embeddings", action="store_true")

    report_p = sub.add_parser("report", help="Print manifest summary as JSON")
    report_p.add_argument(
        "--artifact-dir",
        type=Path,
        default=_env_path("TRACER_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR),
    )

    html_p = sub.add_parser("report-html", help="Generate HTML analysis report")
    html_p.add_argument(
        "--artifact-dir",
        type=Path,
        default=_env_path("TRACER_ARTIFACT_DIR", DEFAULT_ARTIFACT_DIR),
    )
    html_p.add_argument("--output", type=Path, default=None)
    html_p.add_argument("--no-open", action="store_true")

    args = parser.parse_args()
    if args.command == "fit":
        return cmd_fit(
            args.traces,
            args.artifact_dir,
            args.embedder,
            target_ta=args.target_ta,
            batch_size=args.batch_size,
            embeddings_path=args.embeddings,
            reuse_embeddings=args.reuse_embeddings,
        )
    if args.command == "report":
        return cmd_report(args.artifact_dir)
    if args.command == "report-html":
        return cmd_report_html(args.artifact_dir, args.output, open_browser=not args.no_open)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
