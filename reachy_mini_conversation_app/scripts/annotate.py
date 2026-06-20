#!/usr/bin/env python3
"""Local annotation tool for TRACER trace JSONL datasets (stdlib HTTP + embedded HTML)."""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import sys
import webbrowser
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_SCRIPTS_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPTS_DIR.parent
_SRC = _ROOT / "src"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from tracer_dataset_utils import build_row, utc_now_iso  # noqa: E402
from gate_policy_utils import preview_phase2_runtime  # noqa: E402

DEFAULT_TRACES = _ROOT / "tracer_data" / "traces.jsonl"
DEFAULT_SESSION = _ROOT / "tracer_data" / ".annotation_session.jsonl"
PLAY_EMOTION_PATH = (
    _ROOT / "src" / "reachy_mini_conversation_app" / "tools" / "play_emotion.py"
)

MOVE_HEAD_DIRECTIONS = ("left", "right", "up", "down", "front")
FALLBACK_TOP4 = ("chat", "head_tracking:on", "dance", "stop")
FALLBACK_DANCE_MOVES = ("side_to_side_sway",)

EMOTION_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Positives",
        (
            "happy",
            "excited",
            "loving",
            "grateful",
            "success",
            "amazed",
            "relief",
            "calming",
            "surprised",
        ),
    ),
    (
        "Negatives",
        (
            "sad",
            "downcast",
            "lonely",
            "angry",
            "irritated",
            "displeased",
            "disgusted",
            "scared",
            "anxious",
            "embarrassed",
            "impatient",
            "bored",
        ),
    ),
    (
        "Cognitives / neutres",
        (
            "thinking",
            "attentive",
            "confused",
            "uncertain",
            "tired",
            "sleepy",
        ),
    ),
    (
        "Sociales / reponses",
        (
            "greeting",
            "goodbye",
            "welcoming",
            "yes",
            "yes_understanding",
            "no",
            "no_sad",
            "no_excited",
            "no_firm",
            "go_away",
            "helpful",
            "dying",
            "electric",
            "dance",
        ),
    ),
)


def _parse_emotion_intents(path: Path) -> tuple[str, ...]:
    """Extract EMOTION_INTENTS from play_emotion.py without importing it."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        target_name: str | None = None
        value_node: ast.expr | None = None
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    target_name = target.id
                    value_node = node.value
                    break
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name = node.target.id
            value_node = node.value
        if target_name == "EMOTION_INTENTS" and value_node is not None:
            value = ast.literal_eval(value_node)
            if isinstance(value, tuple):
                return tuple(str(v) for v in value)
    raise ValueError(f"EMOTION_INTENTS not found in {path}")


def _load_dance_moves_from_traces(rows: list[dict[str, Any]]) -> list[str]:
    moves: set[str] = set()
    for row in rows:
        teacher = str(row.get("teacher", ""))
        if teacher.startswith("dance:"):
            moves.add(teacher.split(":", 1)[1])
    return sorted(moves)


def _try_import_dance_moves() -> list[str]:
    try:
        from reachy_mini_conversation_app.tools.dance import AVAILABLE_MOVES  # noqa: PLC0415

        return sorted(AVAILABLE_MOVES.keys())
    except Exception:
        return list(FALLBACK_DANCE_MOVES)


class LabelTaxonomy:
    """TRACER label palette, validation, and Top-4 helpers."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.emotion_intents = tuple(
            i for i in _parse_emotion_intents(PLAY_EMOTION_PATH) if i != "random"
        )
        self.annotable_intents = frozenset(self.emotion_intents)
        from_traces = _load_dance_moves_from_traces(rows)
        imported = _try_import_dance_moves()
        dance_named = sorted(set(from_traces) | set(imported) | set(FALLBACK_DANCE_MOVES))
        self.dance_options = ["dance"] + [f"dance:{m}" for m in dance_named]
        self._known_dance_moves = frozenset(dance_named)
        self.default_top4 = self._compute_default_top4(rows)

    def _compute_default_top4(self, rows: list[dict[str, Any]]) -> list[str]:
        counts = Counter(str(r.get("teacher", "chat")) for r in rows)
        top = [label for label, _ in counts.most_common(4)]
        for fallback in FALLBACK_TOP4:
            if len(top) >= 4:
                break
            if fallback not in top:
                top.append(fallback)
        return top[:4]

    def is_valid_teacher(self, teacher: str) -> bool:
        if teacher == "chat" or teacher == "stop" or teacher == "dance":
            return True
        if teacher.startswith("head_tracking:"):
            return teacher in ("head_tracking:on", "head_tracking:off")
        if teacher.startswith("move_head:"):
            direction = teacher.split(":", 1)[1]
            return direction in MOVE_HEAD_DIRECTIONS
        if teacher.startswith("dance:"):
            move = teacher.split(":", 1)[1]
            return bool(move) and move in self._known_dance_moves
        if teacher.startswith("play_emotion:"):
            intent = teacher.split(":", 1)[1]
            return intent in self.annotable_intents
        return False

    def validate_row(self, row: dict[str, Any], *, line_no: int) -> str | None:
        inp = row.get("input")
        teacher = row.get("teacher")
        if not isinstance(inp, str) or not inp.strip():
            return f"Ligne {line_no}: input vide ou absent"
        if not isinstance(teacher, str):
            return f"Ligne {line_no}: teacher doit etre une chaine"
        if not self.is_valid_teacher(teacher):
            return f"Ligne {line_no}: label invalide {teacher!r}"
        return None

    def labels_payload(self) -> dict[str, Any]:
        all_section_intents = {i for _name, intents in EMOTION_SECTIONS for i in intents}
        extra = sorted(set(self.emotion_intents) - all_section_intents)
        sections = [
            {"name": name, "intents": list(intents)} for name, intents in EMOTION_SECTIONS
        ]
        if extra:
            sections.append({"name": "Autres", "intents": extra})

        return {
            "groups": [
                {
                    "id": "conversation",
                    "label": "Conversation",
                    "options": [{"value": "chat", "label": "chat"}],
                },
                {
                    "id": "head_tracking",
                    "label": "Head tracking",
                    "options": [
                        {"value": "head_tracking:on", "label": "on"},
                        {"value": "head_tracking:off", "label": "off"},
                    ],
                },
                {
                    "id": "move_head",
                    "label": "Move head",
                    "options": [
                        {"value": f"move_head:{d}", "label": d} for d in MOVE_HEAD_DIRECTIONS
                    ],
                },
                {
                    "id": "dance",
                    "label": "Dance",
                    "options": [{"value": v, "label": v} for v in self.dance_options],
                },
                {
                    "id": "stop",
                    "label": "Stop",
                    "options": [{"value": "stop", "label": "stop"}],
                },
                {
                    "id": "play_emotion",
                    "label": "Emotion",
                    "sections": sections,
                },
            ],
            "default_top4": self.default_top4,
            "arrow_keys": ["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"],
        }


class AnnotationSession:
    """In-memory annotation state with optional session file persistence."""

    def __init__(
        self,
        traces_path: Path,
        session_path: Path,
        taxonomy: LabelTaxonomy,
    ) -> None:
        self.traces_path = traces_path
        self.session_path = session_path
        self.taxonomy = taxonomy
        self.snapshot: list[dict[str, Any]] = []
        self.log: list[dict[str, Any]] = []
        self._load_snapshot()
        self._load_session_file()

    @property
    def decisions(self) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        for entry in self.log:
            out[int(entry["line_id"])] = entry
        return out

    def _load_snapshot(self) -> None:
        if not self.traces_path.exists():
            raise FileNotFoundError(f"Fichier traces introuvable: {self.traces_path}")
        rows: list[dict[str, Any]] = []
        for line_no, line in enumerate(
            self.traces_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = json.loads(line)
            if "input" not in row:
                raise ValueError(f"Missing 'input' at line {line_no} in {self.traces_path}")
            rows.append(row)
        self.snapshot = rows

    def _load_session_file(self) -> None:
        if not self.session_path.exists():
            return
        for line in self.session_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            self.log.append(json.loads(line))

    def _append_session_entry(self, entry: dict[str, Any]) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rewrite_session_file(self) -> None:
        if not self.log:
            if self.session_path.exists():
                self.session_path.unlink()
            return
        self.session_path.write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.log),
            encoding="utf-8",
        )

    def _record_decision(
        self,
        line_id: int,
        action: str,
        *,
        teacher: str | None = None,
        also_chat: bool | None = None,
        also_head_tracking: bool | None = None,
    ) -> None:
        if line_id < 0 or line_id >= len(self.snapshot):
            raise ValueError(f"line_id hors limites: {line_id}")
        if action not in ("validate", "correct", "delete"):
            raise ValueError(f"action invalide: {action}")
        if action == "correct" and not teacher:
            raise ValueError("teacher requis pour action correct")
        if action == "correct" and not self.taxonomy.is_valid_teacher(teacher or ""):
            raise ValueError(f"label invalide: {teacher}")

        entry: dict[str, Any] = {
            "line_id": line_id,
            "action": action,
            "at": utc_now_iso(),
        }
        if teacher is not None:
            entry["teacher"] = teacher
        if also_chat is not None:
            entry["also_chat"] = also_chat
        if also_head_tracking is not None:
            entry["also_head_tracking"] = also_head_tracking

        self.log.append(entry)
        self._append_session_entry(entry)

    def annotate(
        self,
        line_id: int,
        action: str,
        *,
        teacher: str | None = None,
        also_chat: bool | None = None,
        also_head_tracking: bool | None = None,
    ) -> None:
        self._record_decision(
            line_id,
            action,
            teacher=teacher,
            also_chat=also_chat,
            also_head_tracking=also_head_tracking,
        )

    def undo(self) -> dict[str, Any] | None:
        if not self.log:
            return None
        removed = self.log.pop()
        self._rewrite_session_file()
        return removed

    def is_reviewed(self, line_id: int) -> bool:
        return line_id in self.decisions

    def queue(self, limit: int = 1) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for line_id, row in enumerate(self.snapshot):
            if self.is_reviewed(line_id):
                continue
            items.append(self._queue_item(line_id, row))
            if len(items) >= limit:
                break
        return items

    def _queue_item(self, line_id: int, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "line_id": line_id,
            "input": row.get("input", ""),
            "llm_teacher": row.get("teacher", "chat"),
            "ts": row.get("ts"),
            "also_chat": row.get("also_chat", False),
            "also_head_tracking": row.get("also_head_tracking", False),
            "source_teacher": row.get("source_teacher"),
            "n_tools": row.get("n_tools"),
        }

    def stats(self) -> dict[str, Any]:
        by_action = Counter(d.get("action") for d in self.decisions.values())
        label_counts: Counter[str] = Counter()
        for line_id, decision in self.decisions.items():
            if decision["action"] == "delete":
                continue
            if decision["action"] == "validate":
                label_counts[str(self.snapshot[line_id].get("teacher", "chat"))] += 1
            elif decision["action"] == "correct":
                label_counts[str(decision.get("teacher", ""))] += 1

        top_labels = [{"label": label, "count": count} for label, count in label_counts.most_common(10)]
        remaining = len(self.snapshot) - len(self.decisions)
        return {
            "total": len(self.snapshot),
            "reviewed": len(self.decisions),
            "remaining": remaining,
            "by_action": {
                "validate": by_action.get("validate", 0),
                "correct": by_action.get("correct", 0),
                "delete": by_action.get("delete", 0),
            },
            "top_labels": top_labels,
            "recent": self._recent_decisions(limit=5),
        }

    def _recent_decisions(self, limit: int = 5) -> list[dict[str, Any]]:
        recent: list[dict[str, Any]] = []
        for entry in reversed(self.log):
            line_id = int(entry["line_id"])
            row = self.snapshot[line_id]
            recent.append(
                {
                    "line_id": line_id,
                    "action": entry["action"],
                    "input": row.get("input", "")[:80],
                    "teacher": entry.get("teacher") or row.get("teacher"),
                }
            )
            if len(recent) >= limit:
                break
        return recent

    def top4_labels(self) -> list[str]:
        label_counts: Counter[str] = Counter()
        for line_id, decision in self.decisions.items():
            if decision["action"] == "delete":
                continue
            if decision["action"] == "validate":
                label_counts[str(self.snapshot[line_id].get("teacher", "chat"))] += 1
            elif decision["action"] == "correct":
                label_counts[str(decision.get("teacher", ""))] += 1

        top = [label for label, _ in label_counts.most_common(4)]
        for label in self.taxonomy.default_top4:
            if len(top) >= 4:
                break
            if label not in top:
                top.append(label)
        for fallback in FALLBACK_TOP4:
            if len(top) >= 4:
                break
            if fallback not in top:
                top.append(fallback)
        return top[:4]

    def apply_decisions(self) -> tuple[list[dict[str, Any]], dict[str, int]]:
        output: list[dict[str, Any]] = []
        counts = {"validate": 0, "correct": 0, "delete": 0, "unchanged": 0}

        for line_id, original in enumerate(self.snapshot):
            decision = self.decisions.get(line_id)
            if decision is None:
                output.append(dict(original))
                counts["unchanged"] += 1
                continue

            action = decision["action"]
            if action == "delete":
                counts["delete"] += 1
                continue
            if action == "validate":
                output.append(dict(original))
                counts["validate"] += 1
                continue

            # correct
            new_teacher = str(decision["teacher"])
            also_chat = bool(decision.get("also_chat", False))
            also_head_tracking = bool(decision.get("also_head_tracking", False))
            original_teacher = str(original.get("teacher", "chat"))
            source_teacher = None
            if new_teacher != original_teacher:
                source_teacher = str(original.get("source_teacher") or original_teacher)

            rebuilt = build_row(
                str(original["input"]),
                new_teacher,
                ts=str(original.get("ts")) if original.get("ts") else None,
                also_chat=also_chat,
                also_head_tracking=also_head_tracking,
                source_teacher=source_teacher,
            )
            merged = dict(original)
            merged.update(rebuilt)
            if not also_chat and "also_chat" in merged:
                del merged["also_chat"]
            if not also_head_tracking and "also_head_tracking" in merged:
                del merged["also_head_tracking"]
            if source_teacher is None and "source_teacher" in merged:
                del merged["source_teacher"]
            for key in ("routed_by", "accept_score", "source"):
                if key in original:
                    merged[key] = original[key]
            output.append(merged)
            counts["correct"] += 1

        return output, counts

    def finalize(self) -> dict[str, Any]:
        output, counts = self.apply_decisions()
        for idx, row in enumerate(output, start=1):
            err = self.taxonomy.validate_row(row, line_no=idx)
            if err:
                raise ValueError(err)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        backup_path = self.traces_path.with_name(f"{self.traces_path.name}.bak-{timestamp}")
        shutil.copy2(self.traces_path, backup_path)

        text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output)
        self.traces_path.write_text(text, encoding="utf-8")

        if self.session_path.exists():
            self.session_path.unlink()

        self.log.clear()
        self.snapshot = output

        return {
            "ok": True,
            "backup": str(backup_path),
            "output_lines": len(output),
            "counts": counts,
        }


INDEX_HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Annotation TRACER</title>
<style>
:root {
  --bg: #0f1117;
  --panel: #1a1d27;
  --border: #2d3348;
  --text: #e8ecf4;
  --muted: #8b95ad;
  --accent: #5b8def;
  --green: #3ecf8e;
  --red: #f07178;
  --amber: #e6b450;
  --chat: #5b8def;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", system-ui, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid var(--border);
  background: var(--panel);
}
header h1 { margin: 0; font-size: 1.1rem; font-weight: 600; }
.stats { display: flex; gap: 1rem; color: var(--muted); font-size: 0.9rem; }
.stats strong { color: var(--text); }
main { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
.card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1rem;
}
.input-text {
  font-size: 1.6rem;
  line-height: 1.4;
  font-weight: 500;
  margin: 0 0 1rem;
  word-break: break-word;
}
.teacher-row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; margin-bottom: 0.75rem; }
.badge {
  display: inline-block;
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  font-size: 0.95rem;
  font-weight: 600;
  background: rgba(91,141,239,0.15);
  color: var(--chat);
  border: 1px solid rgba(91,141,239,0.35);
}
.meta { color: var(--muted); font-size: 0.85rem; }
.meta span { margin-right: 1rem; }
.actions { display: flex; gap: 0.75rem; flex-wrap: wrap; margin-top: 1.25rem; }
button {
  cursor: pointer;
  border: none;
  border-radius: 8px;
  padding: 0.75rem 1.25rem;
  font-size: 1rem;
  font-weight: 600;
  transition: opacity 0.15s;
}
button:hover { opacity: 0.88; }
button:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-validate { background: var(--green); color: #0a1a12; }
.btn-delete { background: var(--red); color: #1a0a0a; }
.btn-correct { background: var(--amber); color: #1a1408; }
.btn-secondary { background: var(--border); color: var(--text); }
.btn-top4 {
  flex: 1;
  min-width: 140px;
  background: #252a3a;
  color: var(--text);
  border: 1px solid var(--border);
  text-align: left;
}
.btn-top4 kbd {
  float: right;
  background: #111;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
  font-size: 0.75rem;
  color: var(--muted);
}
.top4-row { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
.palette { display: none; margin-top: 1rem; border-top: 1px solid var(--border); padding-top: 1rem; }
.palette.open { display: block; }
.palette h3 { margin: 0 0 0.75rem; font-size: 0.95rem; color: var(--muted); }
.group { margin-bottom: 1rem; }
.group-title { font-size: 0.85rem; color: var(--muted); margin-bottom: 0.4rem; text-transform: uppercase; letter-spacing: 0.04em; }
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.chip {
  background: #252a3a;
  color: var(--text);
  border: 1px solid var(--border);
  padding: 0.4rem 0.7rem;
  border-radius: 6px;
  font-size: 0.85rem;
}
.chip.selected { border-color: var(--accent); background: rgba(91,141,239,0.2); }
.section-name { font-size: 0.8rem; color: var(--muted); margin: 0.5rem 0 0.3rem; }
.also-chat-row { margin: 0.75rem 0; display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.also-chat-row input { width: 1rem; height: 1rem; }
.preview-box {
  margin: 0.75rem 0; padding: 0.75rem 1rem; border-radius: 8px;
  background: rgba(91,141,239,0.08); border: 1px solid rgba(91,141,239,0.25);
  font-size: 0.9rem; color: var(--muted);
}
.preview-box strong { color: var(--text); }
.btn-shortcut { background: #2a3348; color: var(--text); border: 1px solid var(--border); font-size: 0.85rem; padding: 0.5rem 0.75rem; }
.recent { font-size: 0.85rem; color: var(--muted); }
.recent li { margin: 0.25rem 0; }
.empty { text-align: center; color: var(--muted); padding: 3rem 1rem; }
.footer-actions { display: flex; justify-content: space-between; align-items: center; margin-top: 1rem; }
.shortcuts { font-size: 0.8rem; color: var(--muted); margin-top: 0.75rem; }
.toast {
  position: fixed; bottom: 1rem; right: 1rem;
  background: #252a3a; border: 1px solid var(--border);
  padding: 0.75rem 1rem; border-radius: 8px; display: none;
}
.toast.show { display: block; }
</style>
</head>
<body>
<header>
  <h1>Annotation TRACER</h1>
  <div class="stats">
    <span><strong id="remaining">0</strong> en attente</span>
    <span><strong id="reviewed">0</strong> / <span id="total">0</span></span>
  </div>
</header>
<main>
  <div id="content" class="card">
    <p class="empty">Chargement...</p>
  </div>
  <div class="card">
    <h3 style="margin:0 0 0.75rem;font-size:0.95rem;color:var(--muted)">Top 4 (fleches clavier)</h3>
    <div id="top4" class="top4-row"></div>
  </div>
  <div class="card">
    <h3 style="margin:0 0 0.75rem;font-size:0.95rem;color:var(--muted)">Dernieres decisions</h3>
    <ul id="recent" class="recent"></ul>
  </div>
  <div class="footer-actions">
    <button class="btn-secondary" id="undoBtn">Annuler (U)</button>
    <button class="btn-secondary" id="finalizeBtn">Finaliser</button>
  </div>
  <p class="shortcuts">V valider · D supprimer · C corriger · Fleches Top 4 · U annuler · Entree confirmer palette</p>
</main>
<div id="toast" class="toast"></div>
<script>
let labels = null;
let current = null;
let selectedTeacher = null;
let paletteOpen = false;
const ARROW_KEYS = ["ArrowLeft", "ArrowUp", "ArrowRight", "ArrowDown"];
const ARROW_LABELS = ["\u2190", "\u2191", "\u2192", "\u2193"];

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2500);
}

function renderTop4(top4) {
  const row = document.getElementById("top4");
  row.innerHTML = "";
  top4.forEach((item, i) => {
    const btn = document.createElement("button");
    btn.className = "btn-top4";
    btn.innerHTML = `<span>${item.label}</span> <kbd>${ARROW_LABELS[i]}</kbd>`;
    if (item.count) btn.innerHTML += ` <small style="color:var(--muted)">${item.count}</small>`;
    btn.onclick = () => correctWith(item.label);
    row.appendChild(btn);
  });
}

function renderRecent(recent) {
  const ul = document.getElementById("recent");
  ul.innerHTML = recent.length ? recent.map(r =>
    `<li><strong>${r.action}</strong> — ${escapeHtml(r.input)} → ${escapeHtml(r.teacher || "")}</li>`
  ).join("") : "<li>Aucune decision encore</li>";
}

function escapeHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function renderPalette(groups) {
  return groups.map(g => {
    if (g.sections) {
      const sections = g.sections.map(sec =>
        `<div class="section-name">${sec.name}</div><div class="chips">` +
        sec.intents.map(intent => {
          const val = `play_emotion:${intent}`;
          return `<button class="chip" data-value="${val}" onclick="selectChip('${val}')">${intent}</button>`;
        }).join("") + `</div>`
      ).join("");
      return `<div class="group"><div class="group-title">${g.label}</div>${sections}</div>`;
    }
    const chips = (g.options || []).map(o => {
      const val = typeof o === "string" ? o : o.value;
      const lab = typeof o === "string" ? o : (o.label || o.value);
      return `<button class="chip" data-value="${val}" onclick="selectChip('${val}')">${lab}</button>`;
    }).join("");
    return `<div class="group"><div class="group-title">${g.label || g.id}</div><div class="chips">${chips}</div></div>`;
  }).join("");
}

function renderCurrent(item, { keepPalette = false } = {}) {
  const content = document.getElementById("content");
  if (!item) {
    current = null;
    paletteOpen = false;
    content.innerHTML = `<p class="empty">Toutes les traces sont annotées. Cliquez Finaliser pour écrire le fichier.</p>`;
    return;
  }
  const sameTrace = current && current.line_id === item.line_id;
  current = item;
  if (sameTrace && keepPalette) {
    return;
  }
  const reopenPalette = sameTrace && paletteOpen;
  selectedTeacher = null;
  paletteOpen = false;
  const meta = [];
  if (item.ts) meta.push(`ts: ${item.ts}`);
  if (item.n_tools != null) meta.push(`n_tools: ${item.n_tools}`);
  if (item.also_chat) meta.push("also_chat");
  if (item.also_head_tracking) meta.push("also_head_tracking");
  if (item.source_teacher) meta.push(`source: ${item.source_teacher}`);

  content.innerHTML = `
    <p class="input-text">${escapeHtml(item.input)}</p>
    <div class="teacher-row">
      <span class="meta">Label LLM :</span>
      <span class="badge">${escapeHtml(item.llm_teacher)}</span>
    </div>
    ${meta.length ? `<div class="meta">${meta.map(m => `<span>${escapeHtml(m)}</span>`).join("")}</div>` : ""}
    <div id="policyPreview" class="preview-box"></div>
    <div class="actions">
      <button class="btn-validate" onclick="doAction('validate')">Valider (V)</button>
      <button class="btn-delete" onclick="doAction('delete')">Supprimer (D)</button>
      <button class="btn-correct" onclick="togglePalette()">Corriger (C)</button>
    </div>
    <div id="palette" class="palette">
      <h3>Choisir le label correct</h3>
      <div class="also-chat-row">
        <input type="checkbox" id="alsoChat"${item.also_chat ? " checked" : ""} onchange="updatePreview()">
        <label for="alsoChat">Aussi conversation (also_chat)</label>
        <input type="checkbox" id="alsoHeadTracking"${item.also_head_tracking ? " checked" : ""} onchange="updatePreview()">
        <label for="alsoHeadTracking">Regard (also_head_tracking)</label>
      </div>
      <button class="btn-shortcut" type="button" onclick="applyEmotionPlusTalk()">Emotion + parler (also_chat)</button>
      ${labels ? renderPalette(labels.groups) : ""}
      <div id="palettePreview" class="preview-box"></div>
      <div style="margin-top:0.75rem">
        <button class="btn-correct" onclick="confirmCorrection()">Confirmer (Entree)</button>
      </div>
    </div>
  `;
  updatePreview(item.llm_teacher, item.also_chat, item.also_head_tracking);
  if (reopenPalette) {
    paletteOpen = true;
    document.getElementById("palette").classList.add("open");
  }
}

function selectChip(val) {
  selectedTeacher = val;
  document.querySelectorAll(".chip").forEach(el => {
    el.classList.toggle("selected", el.dataset.value === val);
  });
  updatePreview();
}

function applyEmotionPlusTalk() {
  const chatBox = document.getElementById("alsoChat");
  if (chatBox) chatBox.checked = true;
  updatePreview();
}

async function updatePreview(teacher, alsoChat, alsoHeadTracking) {
  const t = teacher || selectedTeacher || (current && current.llm_teacher) || "chat";
  const chat = alsoChat != null ? alsoChat : (document.getElementById("alsoChat")?.checked || false);
  const track = alsoHeadTracking != null ? alsoHeadTracking : (document.getElementById("alsoHeadTracking")?.checked || false);
  const qs = new URLSearchParams({ teacher: t, also_chat: String(chat), also_head_tracking: String(track) });
  let preview;
  try {
    preview = await api("/api/preview?" + qs.toString());
  } catch (e) {
    preview = { summary: "Preview indisponible" };
  }
  const html = `<strong>Phase 2 (preview)</strong> — ${escapeHtml(preview.summary || "")}`;
  const main = document.getElementById("policyPreview");
  const pal = document.getElementById("palettePreview");
  if (main) main.innerHTML = html;
  if (pal) pal.innerHTML = html;
}

function togglePalette() {
  paletteOpen = true;
  document.getElementById("palette").classList.add("open");
}

async function doAction(action, teacher, alsoChat, alsoHeadTracking) {
  if (!current && action !== "undo") return;
  const body = { line_id: current.line_id, action };
  if (teacher) body.teacher = teacher;
  if (alsoChat != null) body.also_chat = alsoChat;
  if (alsoHeadTracking != null) body.also_head_tracking = alsoHeadTracking;
  await api("/api/annotate", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
  paletteOpen = false;
  await refresh({ forceRerender: true });
}

async function correctWith(teacher) {
  if (!current) return;
  const alsoChat = teacher.startsWith("play_emotion:") ? !!current.also_chat : false;
  const alsoTrack = teacher.startsWith("play_emotion:") ? !!current.also_head_tracking : false;
  await doAction("correct", teacher, alsoChat, alsoTrack);
}

function confirmCorrection() {
  if (!selectedTeacher) { toast("Selectionnez un label"); return; }
  const alsoChat = document.getElementById("alsoChat")?.checked || false;
  const alsoHeadTracking = document.getElementById("alsoHeadTracking")?.checked || false;
  doAction("correct", selectedTeacher, alsoChat, alsoHeadTracking);
}

async function refresh({ forceRerender = false } = {}) {
  const [stats, queueRes, top4Res] = await Promise.all([
    api("/api/stats"),
    api("/api/queue?limit=1"),
    api("/api/top4"),
  ]);
  document.getElementById("remaining").textContent = stats.remaining;
  document.getElementById("reviewed").textContent = stats.reviewed;
  document.getElementById("total").textContent = stats.total;
  renderRecent(stats.recent || []);
  renderTop4(top4Res.items || []);
  const next = (queueRes.items || [])[0] || null;
  const sameTrace = current && next && current.line_id === next.line_id;
  if (forceRerender || !sameTrace) {
    renderCurrent(next);
  } else {
    renderCurrent(next, { keepPalette: paletteOpen });
  }
}

document.getElementById("undoBtn").onclick = async () => {
  await api("/api/undo", { method: "POST" });
  paletteOpen = false;
  await refresh({ forceRerender: true });
  toast("Derniere decision annulee");
};

document.getElementById("finalizeBtn").onclick = async () => {
  if (!confirm("Finaliser ? Un backup sera cree puis traces.jsonl sera reecrit.")) return;
  try {
    const res = await api("/api/finalize", { method: "POST" });
    toast(`Finalise: ${res.counts.validate} validees, ${res.counts.correct} corrigees, ${res.counts.delete} supprimees`);
    await refresh();
  } catch (e) {
    alert("Erreur finalisation: " + e.message);
  }
};

document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  const key = e.key;
  if (key === "v" || key === "V") { e.preventDefault(); doAction("validate"); return; }
  if (key === "d" || key === "D") { e.preventDefault(); doAction("delete"); return; }
  if (key === "c" || key === "C") { e.preventDefault(); togglePalette(); return; }
  if (key === "u" || key === "U") { e.preventDefault(); document.getElementById("undoBtn").click(); return; }
  if (key === "Enter" && paletteOpen && selectedTeacher) { e.preventDefault(); confirmCorrection(); return; }
  const idx = ARROW_KEYS.indexOf(key);
  if (idx >= 0) {
    e.preventDefault();
    const btn = document.querySelectorAll(".btn-top4")[idx];
    if (btn) btn.click();
  }
});

(async () => {
  labels = await api("/api/labels");
  await refresh();
  setInterval(refresh, 1500);
})();
</script>
</body>
</html>
"""


class AnnotationHandler(BaseHTTPRequestHandler):
    """HTTP handler for the annotation API and embedded UI."""

    session: AnnotationSession

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        try:
            if path == "/":
                self._send_html(INDEX_HTML)
            elif path == "/api/labels":
                self._send_json(self.session.taxonomy.labels_payload())
            elif path == "/api/queue":
                limit = int(qs.get("limit", ["1"])[0])
                self._send_json({"items": self.session.queue(limit=limit)})
            elif path == "/api/stats":
                self._send_json(self.session.stats())
            elif path == "/api/top4":
                top4 = self.session.top4_labels()
                counts = {t["label"]: t["count"] for t in self.session.stats()["top_labels"]}
                self._send_json(
                    {
                        "items": [
                            {"label": label, "count": counts.get(label, 0)} for label in top4
                        ]
                    }
                )
            elif path == "/api/preview":
                teacher = qs.get("teacher", ["chat"])[0]
                also_chat = qs.get("also_chat", ["false"])[0].lower() in ("1", "true", "yes")
                also_head = qs.get("also_head_tracking", ["false"])[0].lower() in (
                    "1",
                    "true",
                    "yes",
                )
                self._send_json(
                    preview_phase2_runtime(
                        teacher,
                        also_chat=also_chat,
                        also_head_tracking=also_head,
                    )
                )
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == "/api/annotate":
                data = self._read_json_body()
                self.session.annotate(
                    int(data["line_id"]),
                    str(data["action"]),
                    teacher=data.get("teacher"),
                    also_chat=data.get("also_chat"),
                    also_head_tracking=data.get("also_head_tracking"),
                )
                self._send_json({"ok": True})
            elif path == "/api/undo":
                removed = self.session.undo()
                self._send_json({"ok": True, "removed": removed})
            elif path == "/api/finalize":
                result = self.session.finalize()
                self._send_json(result)
            else:
                self._send_json({"error": "not found"}, status=404)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=400)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)


def main() -> None:
    parser = argparse.ArgumentParser(description="Annotation tool for TRACER traces JSONL")
    parser.add_argument(
        "--traces",
        type=Path,
        default=DEFAULT_TRACES,
        help=f"Path to traces JSONL (default: {DEFAULT_TRACES})",
    )
    parser.add_argument(
        "--session",
        type=Path,
        default=DEFAULT_SESSION,
        help=f"Session file path (default: {DEFAULT_SESSION})",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    traces_path = args.traces.resolve()
    session_path = args.session.resolve()

    snapshot_rows: list[dict[str, Any]] = []
    if traces_path.exists():
        for line in traces_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                snapshot_rows.append(json.loads(line))

    taxonomy = LabelTaxonomy(snapshot_rows)
    session = AnnotationSession(traces_path, session_path, taxonomy)
    AnnotationHandler.session = session

    url = f"http://127.0.0.1:{args.port}/"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), AnnotationHandler)
    print(f"Annotation server: {url}")
    print(f"Traces: {traces_path} ({len(session.snapshot)} lignes)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArret.")
        server.server_close()


if __name__ == "__main__":
    main()
