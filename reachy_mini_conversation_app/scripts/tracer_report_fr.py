"""Rapport HTML TRACER en français avec contexte Reachy Mini (Phase B'')."""

from __future__ import annotations

import html
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: #0d1117; color: #c9d1d9; line-height: 1.6; }
.page { max-width: 1000px; margin: 0 auto; padding: 36px 24px 80px; }
.top-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.logo { font-size: 1rem; font-weight: 700; letter-spacing: .12em;
        color: #58a6ff; text-transform: uppercase; }
h1 { font-size: 1.5rem; font-weight: 700; color: #f0f6fc; }
.subtitle { color: #8b949e; font-size: .875rem; margin-top: 3px; margin-bottom: 24px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
         gap: 14px; margin-bottom: 24px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
        padding: 20px 22px; position: relative; overflow: hidden; }
.card::before { content: ''; position: absolute; top: 0; left: 0; right: 0;
                height: 3px; border-radius: 12px 12px 0 0; }
.card.green::before { background: #238636; }
.card.blue::before  { background: #1f6feb; }
.card.purple::before { background: #8957e5; }
.card.yellow::before { background: #9e6a03; }
.card-label { font-size: .72rem; color: #8b949e; text-transform: uppercase;
              letter-spacing: .1em; font-weight: 600; }
.card-value { font-size: 2rem; font-weight: 800; color: #f0f6fc; margin: 4px 0 2px; }
.card.green .card-value { color: #3fb950; }
.card.blue  .card-value { color: #58a6ff; }
.card.purple .card-value { color: #bc8cff; }
.card.yellow .card-value { color: #d29922; }
.card-sub { font-size: .75rem; color: #8b949e; }
.context { background: #161b22; border: 1px solid #30363d; border-left: 4px solid #1f6feb;
           border-radius: 12px; padding: 20px 22px; margin-bottom: 20px; }
.context h2 { font-size: .95rem; color: #f0f6fc; text-transform: none; letter-spacing: 0;
              margin-bottom: 12px; }
.context p, .context li { font-size: .875rem; color: #c9d1d9; margin-bottom: 8px; }
.context ul { padding-left: 1.25rem; margin-bottom: 8px; }
.context strong { color: #f0f6fc; }
.context .hint { color: #8b949e; font-size: .8rem; }
.hint { color: #8b949e; font-size: .8rem; }
.status-ok { color: #3fb950; font-weight: 700; }
.status-warn { color: #d29922; font-weight: 700; }
.glossary { display: grid; gap: 10px; }
.glossary dt { color: #58a6ff; font-weight: 600; font-size: .84rem; }
.glossary dd { color: #8b949e; font-size: .82rem; margin: 0 0 8px 0; padding-left: 0; }
.coverage-wrap { display: flex; align-items: center; gap: 32px; margin-bottom: 24px;
                 background: #161b22; border: 1px solid #30363d; border-radius: 12px;
                 padding: 24px 28px; flex-wrap: wrap; }
.ring-svg { flex-shrink: 0; }
.ring-stats { flex: 1; min-width: 240px; }
.ring-stats h3 { font-size: .8rem; font-weight: 600; color: #8b949e; text-transform: uppercase;
                 letter-spacing: .08em; margin-bottom: 14px; }
.ring-row { display: flex; justify-content: space-between; align-items: center;
            padding: 6px 0; border-bottom: 1px solid #21262d; font-size: .875rem; }
.ring-row:last-child { border-bottom: none; }
.ring-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block;
            margin-right: 8px; flex-shrink: 0; }
.ring-row-label { display: flex; align-items: center; color: #c9d1d9; }
.ring-row-val { font-weight: 600; color: #f0f6fc; }
.section { background: #161b22; border: 1px solid #30363d; border-radius: 12px;
           padding: 22px 24px; margin-bottom: 20px; }
h2 { font-size: .82rem; font-weight: 600; color: #8b949e; text-transform: uppercase;
     letter-spacing: .1em; margin-bottom: 16px; }
.section-intro { font-size: .82rem; color: #8b949e; margin-bottom: 14px; }
table { width: 100%; border-collapse: collapse; font-size: .84rem; }
th { text-align: left; color: #8b949e; font-weight: 500; font-size: .75rem;
     text-transform: uppercase; letter-spacing: .07em; padding: 0 8px 10px 0;
     border-bottom: 1px solid #30363d; }
td { padding: 9px 8px 9px 0; border-bottom: 1px solid #1c2128; vertical-align: middle; }
tr:last-child td { border-bottom: none; }
tr:hover td { background: #1c2128; }
.bar-bg { background: #21262d; border-radius: 3px; height: 6px; min-width: 80px; }
.bar-fill { height: 6px; border-radius: 3px; }
.bar-high { background: #238636; }
.bar-mid  { background: #9e6a03; }
.bar-low  { background: #b91c1c; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 20px;
         font-size: .72rem; font-weight: 600; }
.b-green  { background: #0f2e17; color: #3fb950; border: 1px solid #238636; }
.b-blue   { background: #0c1e3a; color: #58a6ff; border: 1px solid #1f6feb; }
.b-purple { background: #1d1135; color: #bc8cff; border: 1px solid #8957e5; }
.b-gray   { background: #21262d; color: #8b949e; border: 1px solid #30363d; }
.filter-row { display: flex; gap: 10px; margin-bottom: 14px; }
.search { background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
          padding: 6px 12px; color: #c9d1d9; font-size: .84rem; flex: 1; outline: none; }
.search:focus { border-color: #58a6ff; }
.filter-count { font-size: .78rem; color: #8b949e; align-self: center; white-space: nowrap; }
.pair { background: #0d1117; border-radius: 10px; padding: 14px 16px;
        margin-bottom: 10px; border: 1px solid #21262d; }
.pair-intent { font-size: .72rem; font-weight: 700; color: #8b949e;
               text-transform: uppercase; letter-spacing: .08em; margin-bottom: 10px; }
.pair-row { display: flex; gap: 10px; align-items: flex-start; margin-bottom: 6px; }
.pair-row:last-child { margin-bottom: 0; }
.pair-tag { font-size: .7rem; font-weight: 700; padding: 3px 9px; border-radius: 4px;
            white-space: nowrap; min-width: 88px; text-align: center; }
.pt-local    { background: #0f2e17; color: #3fb950; border: 1px solid #238636; }
.pt-deferred { background: #2d1516; color: #f85149; border: 1px solid #b91c1c; }
.pair-text { font-size: .84rem; color: #c9d1d9; line-height: 1.5; flex: 1; }
.pair-score { font-size: .75rem; color: #8b949e; margin-left: 6px; white-space: nowrap; }
.ex-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 700px) { .ex-grid { grid-template-columns: 1fr; } }
.ex-col h3 { font-size: .75rem; color: #8b949e; text-transform: uppercase;
             letter-spacing: .08em; margin-bottom: 10px; }
.ex-item { background: #0d1117; border: 1px solid #21262d; border-radius: 8px;
           padding: 12px 14px; margin-bottom: 8px; }
.ex-item.handled { border-left: 3px solid #238636; }
.ex-item.deferred { border-left: 3px solid #b91c1c; }
.ex-text { font-size: .84rem; color: #c9d1d9; margin-bottom: 6px; line-height: 1.4; }
.ex-meta { display: flex; gap: 8px; flex-wrap: wrap; }
.ex-label { font-size: .72rem; background: #21262d; border-radius: 4px;
            padding: 2px 7px; color: #8b949e; }
.ex-score { font-size: .72rem; color: #8b949e; }
.checklist { list-style: none; padding: 0; }
.checklist li { padding: 8px 0; border-bottom: 1px solid #21262d; font-size: .84rem; }
.checklist li:last-child { border-bottom: none; }
.footer { margin-top: 48px; text-align: center; font-size: .78rem; color: #484f58; }
.footer a { color: #58a6ff; text-decoration: none; }
"""

_JS = """
document.addEventListener('DOMContentLoaded', function() {
    var input = document.getElementById('label-search');
    if (!input) return;
    input.addEventListener('input', function() {
        var q = this.value.toLowerCase();
        var rows = document.querySelectorAll('#label-table tbody tr');
        var visible = 0;
        rows.forEach(function(row) {
            var show = row.textContent.toLowerCase().includes(q);
            row.style.display = show ? '' : 'none';
            if (show) visible++;
        });
        var count = document.getElementById('label-count');
        if (count) count.textContent = visible + ' sur ' + rows.length + ' labels';
    });
});
"""

_METHOD_BADGE = {"global": "b-green", "l2d": "b-blue", "rsb": "b-purple"}

_LABEL_HINTS: dict[str, str] = {
    "chat": "Conversation — le LLM répond (pas de bypass silencieux en Phase C).",
    "dance": "Commande « danse » — exécution locale silencieuse si acceptée.",
    "stop": "Arrêt danse + émotion — double tool en Phase C.",
    "head_tracking:on": "Suis-moi du regard — tool head_tracking start=true.",
    "head_tracking:off": "Arrête de me regarder — head_tracking start=false.",
    "move_head:left": "Tourne la tête à gauche.",
    "move_head:right": "Tourne la tête à droite.",
    "move_head:up": "Regarde en haut.",
    "move_head:down": "Regarde en bas.",
    "move_head:front": "Regarde devant.",
}


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "—"


def _bar_html(rate: float) -> str:
    pct = int(rate * 100)
    cls = "bar-high" if rate >= 0.85 else "bar-mid" if rate >= 0.60 else "bar-low"
    return (
        f'<div class="bar-bg"><div class="{cls} bar-fill" style="width:{pct}%"></div></div>'
    )


def _score_str(score: float | None) -> str:
    if score is None:
        return ""
    return f'<span class="pair-score">score {_esc(f"{score:.2f}")}</span>'


def _label_hint(label: str) -> str:
    if label in _LABEL_HINTS:
        return _LABEL_HINTS[label]
    if label.startswith("play_emotion:"):
        intent = label.split(":", 1)[1]
        return f"Émotion « {intent} » — tool play_emotion."
    return ""


def _read_embedder(artifact_dir: Path) -> str | None:
    path = artifact_dir / "embedder.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def _dataset_stats(root: Path) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for name in ("traces.jsonl", "traces_synthetic.jsonl", "traces_all.jsonl"):
        path = root / "tracer_data" / name
        if path.exists():
            stats[name] = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return stats


def generate_html_report_fr(
    artifact_dir: str | Path,
    output_path: str | Path | None = None,
    *,
    project_root: str | Path | None = None,
) -> str:
    """Génère report.html en français avec contexte Reachy Mini."""
    artifact_dir = Path(artifact_dir)
    if output_path is None:
        output_path = artifact_dir / "report.html"
    output_path = Path(output_path)
    root = Path(project_root) if project_root else artifact_dir.parent.parent

    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))
    qr_path = artifact_dir / "qualitative_report.json"
    qr = json.loads(qr_path.read_text(encoding="utf-8")) if qr_path.exists() else None

    method = manifest.get("selected_method") or "aucun"
    coverage = manifest.get("coverage_cal")
    ta = manifest.get("teacher_agreement_cal")
    n_traces = manifest.get("n_traces", 0)
    n_labels = len(manifest.get("label_space", []))
    emb_dim = manifest.get("embedding_dim")
    target_ta = manifest.get("target_teacher_agreement", 0.90)
    method_cls = _METHOD_BADGE.get(method, "b-gray")
    embedder = _read_embedder(artifact_dir)
    ds = _dataset_stats(root)

    cov_exact = (coverage or 0) * 100
    defer_exact = 100 - cov_exact
    ta_ok = ta is not None and ta >= target_ta - 1e-6
    ta_status = "status-ok" if ta_ok else "status-warn"
    generated_at = datetime.now(UTC).strftime("%d/%m/%Y %H:%M UTC")

    r, cx, cy, sw = 42, 56, 56, 24
    circumf = 2 * math.pi * r
    green_len = circumf * (coverage or 0)
    gap_len = circumf - green_len

    ring_svg = f"""
<svg class="ring-svg" width="112" height="112" viewBox="0 0 112 112">
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#b91c1c" stroke-width="{sw}"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#238636" stroke-width="{sw}"
          stroke-dasharray="{green_len:.2f} {gap_len:.2f}" transform="rotate(-90 {cx} {cy})"/>
  <text x="{cx}" y="{cy - 6}" text-anchor="middle" fill="#f0f6fc"
        font-size="15" font-weight="800">{cov_exact:.1f}%</text>
  <text x="{cx}" y="{cy + 12}" text-anchor="middle" fill="#8b949e"
        font-size="9" letter-spacing="1">géré</text>
</svg>"""

    ds_lines = []
    if ds.get("traces.jsonl"):
        ds_lines.append(f"{ds['traces.jsonl']} traces réelles (collecte live)")
    if ds.get("traces_synthetic.jsonl"):
        ds_lines.append(f"{ds['traces_synthetic.jsonl']} traces synthétiques (bootstrap)")
    if ds.get("traces_all.jsonl"):
        ds_lines.append(f"{ds['traces_all.jsonl']} traces fusionnées (fit)")

    html_doc = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TRACER — Rapport Reachy Mini</title>
<style>{_CSS}</style>
</head>
<body>
<div class="page">

<div class="top-bar">
  <span class="logo">TRACER</span>
  <span style="color:#30363d">|</span>
  <span style="font-size:.875rem;color:#8b949e">Reachy Mini — Intent Gate (Phase B'')</span>
</div>
<h1>Politique de routage d'intentions</h1>
<div class="subtitle">
  {_esc(f"{n_traces:,}".replace(",", " "))} traces &nbsp;·&nbsp; {n_labels} labels
  &nbsp;·&nbsp; embeddings {emb_dim}D
  &nbsp;·&nbsp; cible parité = {_pct(target_ta)}
  &nbsp;·&nbsp; généré le {_esc(generated_at)}
</div>

<div class="context">
  <h2>À quoi sert ce rapport ?</h2>
  <p>
    Ce modèle TRACER apprend à partir du dataset <code>traces_all.jsonl</code> (entrée utilisateur → label « teacher »).
    En <strong>Phase C</strong>, chaque phrase parlée sera classée localement :
  </p>
  <ul>
    <li><strong>Géré (surrogate)</strong> + label <em>commande</em> (≠ <code>chat</code>) → exécution <strong>silencieuse</strong> du tool (bypass LLM).</li>
    <li><strong>Déféré</strong> ou label <code>chat</code> → comportement actuel : le <strong>LLM répond</strong> (avec ou sans tools).</li>
  </ul>
  <p class="hint">
    Dataset : {' — '.join(_esc(x) for x in ds_lines) if ds_lines else 'non trouvé dans tracer_data/'}.
    {f' Embedder : <code>{_esc(embedder)}</code>.' if embedder else ''}
  </p>
</div>

<div class="context">
  <h2>Comment lire les métriques</h2>
  <dl class="glossary">
    <dt>Couverture (calibrée)</dt>
    <dd>Part des phrases où TRACER ose une décision locale. Le reste part au LLM par prudence. 30–70 % est courant ; plus c'est haut, plus de tours court-circuitent le LLM.</dd>
    <dt>Parité teacher (TA, calibrée)</dt>
    <dd>Sur le trafic <em>géré</em>, % de prédictions identiques au label du dataset. Objectif projet : <strong>≥ {_pct(target_ta)}</strong>. En dessous : enrichir le bootstrap ou corriger les labels.</dd>
    <dt>Score d'acceptation</dt>
    <dd>Confiance du routeur (0–1). Sous le seuil calibré → déféré au LLM même si la classe est devinée.</dd>
    <dt>Paires limites (boundary pairs)</dt>
    <dd>Deux phrases proches, même label teacher, mais l'une est gérée et l'autre déférée. Utile pour repérer formulations ambiguës ou pièges lexicaux.</dd>
  </dl>
</div>

<div class="cards">
  <div class="card green">
    <div class="card-label">Couverture</div>
    <div class="card-value">{_pct(coverage)}</div>
    <div class="card-sub">géré par le surrogate</div>
  </div>
  <div class="card blue">
    <div class="card-label">Parité teacher</div>
    <div class="card-value {ta_status}">{_pct(ta)}</div>
    <div class="card-sub">sur le trafic géré (cible {_pct(target_ta)})</div>
  </div>
  <div class="card purple">
    <div class="card-label">Méthode</div>
    <div class="card-value" style="font-size:1.2rem;margin-top:10px">
      <span class="badge {method_cls}">{_esc(method.upper())}</span>
    </div>
    <div class="card-sub">pipeline sélectionné</div>
  </div>
  <div class="card yellow">
    <div class="card-label">Appels LLM évités</div>
    <div class="card-value">{_pct(coverage)}</div>
    <div class="card-sub">vs baseline 100 % LLM (estimation)</div>
  </div>
</div>

<div class="coverage-wrap">
  {ring_svg}
  <div class="ring-stats">
    <h3>Répartition du trafic (jeu de calibration)</h3>
    <div class="ring-row">
      <div class="ring-row-label"><span class="ring-dot" style="background:#238636"></span>Géré localement</div>
      <div class="ring-row-val" style="color:#3fb950">{_pct(coverage)}</div>
    </div>
    <div class="ring-row">
      <div class="ring-row-label"><span class="ring-dot" style="background:#b91c1c"></span>Déféré au LLM</div>
      <div class="ring-row-val" style="color:#f85149">{defer_exact:.1f} %</div>
    </div>
    <div class="ring-row">
      <div class="ring-row-label"><span class="ring-dot" style="background:#58a6ff"></span>Parité teacher (géré)</div>
      <div class="ring-row-val">{_pct(ta)}</div>
    </div>
    <div class="ring-row">
      <div class="ring-row-label"><span class="ring-dot" style="background:#8b949e"></span>Labels distincts</div>
      <div class="ring-row-val">{n_labels}</div>
    </div>
  </div>
</div>
"""

    if qr is None:
        html_doc += "<p style='color:#8b949e'>Aucun rapport qualitatif dans cet artifact.</p>"
    else:
        slices = qr.get("slices", [])
        label_slices = [s for s in slices if s["slice_name"].startswith("label:")]
        length_slices = [s for s in slices if s["slice_name"].startswith("length:")]
        pairs = qr.get("boundary_pairs", [])
        handled_ex = qr.get("handled_examples", [])
        deferred_ex = qr.get("deferred_examples", [])

        try:
            from tracer.analysis.sankey import generate_sankey_div

            sankey_div = generate_sankey_div(artifact_dir)
            if sankey_div:
                html_doc += f"""
<div class="section">
  <h2>Flux de routage</h2>
  <p class="section-intro">
    Vert = géré par TRACER. Rouge = déféré au LLM. Survolez un lien pour les effectifs exacts.
  </p>
  {sankey_div}
</div>
"""
        except Exception:
            pass

        html_doc += f"""
<div class="section">
  <h2>Checklist avant Phase C</h2>
  <ul class="checklist">
    <li>{'✅' if ta_ok else '⚠️'} Parité teacher ≥ {_pct(target_ta)} sur trafic géré</li>
    <li>🔍 Pièges <code>chat</code> : « Je déteste les lundis », « Pourquoi tu me regardes ? » → doivent rester <strong>déférés</strong> ou classés <code>chat</code></li>
    <li>🔍 Commandes claires : « Regarde-moi », « Danse », « Stop », « Fais le triste » → doivent être <strong>gérées</strong> avec le bon label</li>
    <li>📋 Relire les 119 traces réelles dans <code>traces.jsonl</code> (surtout <code>also_chat</code>)</li>
  </ul>
</div>
"""

        html_doc += f"""
<div class="section">
  <h2>Couverture par label ({len(label_slices)} labels affichés)</h2>
  <p class="section-intro">
    <strong>Couverture</strong> = % de phrases de ce label gérées localement.
    <strong>TA (géré)</strong> = précision vs le teacher sur ce sous-ensemble.
    Couverture basse sur une commande = bypass rare mais sûr (le LLM prend le relais).
  </p>
  <div class="filter-row">
    <input id="label-search" class="search" placeholder="Filtrer les labels…" type="text">
    <span class="filter-count" id="label-count">{len(label_slices)} sur {len(label_slices)} labels</span>
  </div>
  <table id="label-table">
    <thead>
      <tr>
        <th>Label</th>
        <th>Couverture</th>
        <th style="width:130px"></th>
        <th>N</th>
        <th>TA (géré)</th>
      </tr>
    </thead>
    <tbody>
"""
        for s in sorted(label_slices, key=lambda x: -x["handled_rate"]):
            label = s["slice_name"].replace("label:", "")
            hr_v = s["handled_rate"]
            ta_s = s.get("teacher_agreement_handled")
            ta_str = f"{ta_s:.1%}" if ta_s is not None else "—"
            hint = _label_hint(label)
            hint_html = f'<br><span class="hint">{_esc(hint)}</span>' if hint else ""
            html_doc += (
                f"<tr><td><code>{_esc(label)}</code>{hint_html}</td>"
                f"<td><b style='color:#f0f6fc'>{hr_v:.1%}</b></td>"
                f"<td>{_bar_html(hr_v)}</td>"
                f"<td style='color:#8b949e'>{s['count']}</td>"
                f"<td style='color:#8b949e'>{ta_str}</td></tr>\n"
            )
        html_doc += "    </tbody>\n  </table>\n</div>\n"

        if length_slices:
            length_labels = {"length:short": "Courte", "length:medium": "Moyenne", "length:long": "Longue"}
            html_doc += (
                '<div class="section">\n<h2>Couverture par longueur de phrase</h2>\n'
                '<p class="section-intro">Les phrases longues conversationnelles sont souvent plus ambiguës.</p>\n'
                "<table>\n"
                "<tr><th>Longueur</th><th>Couverture</th><th style='width:130px'></th><th>N</th></tr>\n"
            )
            for s in length_slices:
                name = length_labels.get(s["slice_name"], s["slice_name"])
                html_doc += (
                    f"<tr><td>{_esc(name)}</td>"
                    f"<td><b style='color:#f0f6fc'>{s['handled_rate']:.1%}</b></td>"
                    f"<td>{_bar_html(s['handled_rate'])}</td>"
                    f"<td style='color:#8b949e'>{s['count']}</td></tr>\n"
                )
            html_doc += "</table>\n</div>\n"

        if pairs:
            html_doc += f"""
<div class="section">
  <h2>Paires limites contrastées ({len(pairs)})</h2>
  <p class="section-intro">
    Même label teacher, décisions opposées. La phrase <strong>gérée</strong> sera routée localement en Phase C
    (si c'est une commande) ; la phrase <strong>déférée</strong> passera au LLM — comportement souhaité pour les formulations floues.
  </p>
"""
            for p in pairs[:12]:
                hs = _score_str(p.get("handled_score"))
                ds = _score_str(p.get("deferred_score"))
                hint = _label_hint(p.get("teacher_label", ""))
                hint_p = f'<div class="hint" style="margin-bottom:8px">{_esc(hint)}</div>' if hint else ""
                html_doc += f"""<div class="pair">
  <div class="pair-intent">{_esc(p.get('teacher_label', ''))}</div>
  {hint_p}
  <div class="pair-row">
    <span class="pair-tag pt-local">GÉRÉ</span>
    <span class="pair-text">{_esc(p.get('handled_preview', ''))}</span>{hs}
  </div>
  <div class="pair-row">
    <span class="pair-tag pt-deferred">→ LLM</span>
    <span class="pair-text">{_esc(p.get('deferred_preview', ''))}</span>{ds}
  </div>
</div>
"""
            html_doc += "</div>\n"

        if handled_ex or deferred_ex:
            html_doc += """
<div class="section">
  <h2>Exemples représentatifs</h2>
  <p class="section-intro">
    Échantillon du jeu de fit. Les exemples <em>déférés</em> montrent des variantes que TRACER refuse de gérer seul (conservateur = bien pour éviter les faux bypass).
  </p>
  <div class="ex-grid">
"""
            html_doc += "<div class='ex-col'><h3>Géré par TRACER</h3>\n"
            for ex in handled_ex[:6]:
                score = ex.get("accept_score")
                score_html = (
                    f'<span class="ex-score">score {score:.2f}</span>' if score is not None else ""
                )
                html_doc += (
                    f'<div class="ex-item handled">'
                    f'<div class="ex-text">{_esc(ex.get("input_preview", ""))}</div>'
                    f'<div class="ex-meta"><span class="ex-label">{_esc(ex.get("teacher_label", ""))}</span>'
                    f"{score_html}</div></div>\n"
                )
            html_doc += "</div>\n"

            html_doc += "<div class='ex-col'><h3>Déféré au LLM</h3>\n"
            for ex in deferred_ex[:6]:
                html_doc += (
                    f'<div class="ex-item deferred">'
                    f'<div class="ex-text">{_esc(ex.get("input_preview", ""))}</div>'
                    f'<div class="ex-meta"><span class="ex-label">{_esc(ex.get("teacher_label", ""))}</span>'
                    f"</div></div>\n"
                )
            html_doc += "</div>\n</div>\n</div>\n"

    html_doc += f"""
<div class="footer">
  Rapport Reachy Mini — généré par <code>scripts/tracer_report_fr.py</code>
  &nbsp;·&nbsp; <a href="https://github.com/adrida/tracer">tracer-llm</a>
  &nbsp;·&nbsp; Voir aussi <code>manifest.json</code> et <code>qualitative_report.json</code>
</div>

</div>
<script>{_JS}</script>
</body>
</html>"""

    output_path.write_text(html_doc, encoding="utf-8")

    try:
        from tracer.analysis.sankey import generate_sankey

        generate_sankey(artifact_dir, output_path=artifact_dir / "sankey.html", fmt="html")
    except Exception:
        pass

    return str(output_path)
