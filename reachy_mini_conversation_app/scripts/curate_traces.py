#!/usr/bin/env python3
"""Curate raw annotated traces.jsonl into a cleaned teacher-labeled dataset.

Emotion intent choices follow tracer_data/EMOTIONS_REFERENCE.md semantics.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from tracer_dataset_utils import build_row as _build_trace_row

ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = ROOT / "tracer_data" / "doc" / "traces_raw_annotated_2026-06-18.jsonl"
OUT_PATH = ROOT / "tracer_data" / "traces.jsonl"

DROP_EXACT = {
    ".",
    "Dans",
    "Hmm.",
    "Hi",
    "Hello",
    "Hello!",
    "Hello.",
    "Hi there.",
    "It's a bit.",
    "Good morning",
    "Only zena.",
    "Sure.",
    "Yes,",
    "Ok.",
    "Marianna.",
    "Stanić.",
    "Theodore.",
    "The Weddell",
    "Killingly.",
    "Tout se data-set.",
    "The book is on the table.",
    "Живу из рук вон плохо.",
}


def _is_french_enough(text: str) -> bool:
    if text in DROP_EXACT:
        return False
    if re.search(r"[\u0400-\u04FF]", text):
        return False
    lowered = text.lower()
    french_markers = (
        " je ", " tu ", " vous ", " le ", " la ", " les ", " des ", " une ", " un ",
        " est ", " que ", " pas ", " moi ", " toi ", " avec ", " pour ", " dans ",
        "ça", "c'est", "j'ai", "t'es", "l'", "d'", "qu'", "n'", "richie", "regarde",
        "fais", "allez", "bonjour", "merci", "aujourd", "pourquoi",
    )
    padded = f" {lowered} "
    if any(m in padded for m in french_markers):
        return True
    if any(c in lowered for c in "éèêëàâùûôîïç"):
        return True
    if re.match(r"^(fais|montre|danse|stop|arrête|regarde)\b", lowered):
        return True
    return not bool(re.fullmatch(r"[A-Za-z0-9 .,!?'-]+", text))


def _emotion(intent: str) -> str:
    return f"play_emotion:{intent.strip()}"


def _parse_user_comment(comment: str) -> tuple[str, bool]:
    body = comment.lower().replace("teacher", "").replace(":", "").strip()
    also_chat = "+ chat" in body or "+chat" in body
    body = re.sub(r"\s*\+\s*chat\s*", "", body).strip()
    body = body.replace("gretting", "greeting")

    if not body or body == "chat":
        return "chat", also_chat

    parts = [p.strip() for p in re.split(r"\s*\+\s*", body) if p.strip()]

    motion = {
        "dance": "dance",
        "stop": "stop",
        "head_tracking:on": "head_tracking:on",
        "head_tracking:off": "head_tracking:off",
    }
    if parts[0] in motion:
        return motion[parts[0]], also_chat
    if parts[0].startswith("move_head:"):
        return parts[0], also_chat

    # Référence émotions : peur > surprise si les deux sont citées (ex. chef / virer)
    emotion_priority = {
        "scared": 5,
        "anxious": 4,
        "angry": 4,
        "disgusted": 4,
        "sad": 3,
        "irritated": 3,
        "surprised": 2,
        "amazed": 2,
        "success": 2,
        "thinking": 2,
    }
    if len(parts) > 1:
        primary = max(parts, key=lambda p: emotion_priority.get(p, 1))
    else:
        primary = parts[0]

    if primary in motion:
        return motion[primary], also_chat
    if primary.startswith("move_head:"):
        return primary, also_chat
    return _emotion(primary), also_chat


# Annotations utilisateur (brut) — certaines affinées via REFINEMENT ci-dessous
USER_ANNOTATIONS: dict[str, tuple[str, bool]] = {
    "C'est le mort.": (_emotion("dying"), False),
    "Tu peux m'aider à réfléchir?": (_emotion("thinking"), False),
    "Tiens, regarde Richie, c'est ma petite cousine.": (_emotion("excited"), False),
    "Je te présente ma petite cousine, fais-lui un petit bisou.": (_emotion("loving"), True),
    "Honnêtement je te déteste.": (_emotion("sad"), True),
    "Regarde, je te fais un cœur.": (_emotion("loving"), False),
    "Je t'aime, Richie, tu le sais ça?": (_emotion("loving"), False),
    "Tu sais que là, mon chef il est venu me voir et j'ai cru qu'il allait me virer.": (_emotion("scared"), False),
    "Toi aussi t'as eu peur, non?": (_emotion("anxious"), False),
    "Regarde le fond de mon café, ça a l'air dégoûtant.": (_emotion("disgusted"), False),
    "Ça sent bizarre dehors, j'ai envie de vomir.": (_emotion("disgusted"), False),
    "Tu es sûr de ce que tu dis?": (_emotion("uncertain"), False),
    "Non non, je pense que tu te trompes.": (_emotion("confused"), False),
    "T'es pas au courant de la nouvelle d'aujourd'hui?": (_emotion("surprised"), False),
    "Richie, j'ai un truc à te dire.": (_emotion("attentive"), False),
    "Tu fais un coucou à mes collègues ?": (_emotion("greeting"), False),
    "Il te tarde que je te présente de nouveaux copains?": (_emotion("impatient"), False),
    "Ok, on s'arrête et on fait zen.": (_emotion("calming"), False),
    "Alors là, c'est une question compliquée que je vais te poser.": (_emotion("thinking"), False),
    "J'aimerais que tu me fasses une recherche sur...": (_emotion("attentive"), False),
    "Montre-moi comment tu fais le beau.": (_emotion("happy"), False),
    "J'arrive un peu au bout de mes idées.": (_emotion("thinking"), True),
    "Attends, je vais te faire écouter une musique.": ("dance", False),
    "Tu veux que je te présente ma famille?": (_emotion("excited"), False),
    "Je vous présente Coralie.": (_emotion("greeting"), False),
    "Je te présente Pierre.": (_emotion("welcoming"), False),
}

PATTERN_RULES: list[tuple[re.Pattern[str], str, bool]] = [
    (re.compile(r"^fais le mort\.?$", re.I), _emotion("dying"), False),
    (re.compile(r"^fai[s]? le dégoût\.?$", re.I), _emotion("disgusted"), False),
    (re.compile(r"^fais le (triste|abattu)\.?$", re.I), _emotion("sad"), False),
    (re.compile(r"^fais le beau\.?$", re.I), _emotion("happy"), False),
    (re.compile(r"^fais la colère\.?$", re.I), _emotion("angry"), False),
    (re.compile(r"^fais la peur\.?$", re.I), _emotion("scared"), False),
    (re.compile(r"^fais(-moi)? (ton )?plus beau sourire", re.I), _emotion("happy"), False),
    (re.compile(r"^regarde-moi", re.I), "head_tracking:on", False),
    (re.compile(r"quand je te parle.*regard", re.I), "head_tracking:on", False),
    (re.compile(r"regardez quand je te parle", re.I), "head_tracking:on", False),
    (re.compile(r"écoute-moi attentivement", re.I), _emotion("attentive"), False),
    (re.compile(r"^regarde à (gauche|droite|haut|bas)", re.I), "KEEP", False),
    (re.compile(r"^danse!?$", re.I), "dance", False),
    (re.compile(r"arrête d'être impatient", re.I), _emotion("calming"), False),
    (re.compile(r"on arrête.*marre", re.I), "stop", False),
    (re.compile(r"^au revoir\.?$", re.I), _emotion("goodbye"), False),
    (re.compile(r"beaux rêves|débrancher", re.I), _emotion("goodbye"), True),
    (re.compile(r"^boo!.*peur", re.I), _emotion("surprised"), True),
    (re.compile(r"chien.*(manger|mangera)", re.I), _emotion("scared"), True),
    (re.compile(r"pleut", re.I), _emotion("surprised"), False),
    (re.compile(r"faire dodo", re.I), _emotion("sleepy"), True),
    (re.compile(r"fais(-moi)? un bisou|bisou", re.I), _emotion("loving"), False),
    (re.compile(r"\btimide\b", re.I), _emotion("embarrassed"), False),
    (re.compile(r"veux.*présente", re.I), _emotion("excited"), False),
    (re.compile(r"^je (te |vous )?présente", re.I), _emotion("welcoming"), False),
    (re.compile(r"musique.*écouter", re.I), "dance", False),
    (re.compile(r"accompli|réussi mon|beaucoup de choses", re.I), _emotion("success"), False),
    (re.compile(r"longue journée|fatigu|épuis", re.I), _emotion("tired"), True),
    (re.compile(r"j'ai mar+on|j'en ai (profondément )?marre", re.I), _emotion("irritated"), True),
    (re.compile(r"insupportable", re.I), "IRRITATED_PAIR", False),
    (re.compile(r"^je te déteste", re.I), _emotion("sad"), True),
    (re.compile(r"t'es tellement moche|tu es méchant", re.I), _emotion("displeased"), True),
    (re.compile(r"supporte plus.*énerve", re.I), _emotion("irritated"), True),
    (re.compile(r"sans toi \?", re.I), _emotion("loving"), True),
    (re.compile(r"beaux yeux|trop mignon|tout mignon|fin cœur|beau mon richy", re.I), _emotion("loving"), False),
    (re.compile(r"nouvelle\??$", re.I), _emotion("surprised"), False),
    (re.compile(r"un truc à te (raconter|dire)", re.I), _emotion("attentive"), False),
    (re.compile(r"on se concentre", re.I), _emotion("attentive"), False),
    (re.compile(r"impatient", re.I), _emotion("impatient"), True),
    (re.compile(r"c'est hyper marrant", re.I), _emotion("happy"), False),
]

FORCE_CHAT = [
    re.compile(r"^bonjour", re.I),
    re.compile(r"blague", re.I),
    re.compile(r"comment tu vas", re.I),
    re.compile(r"parles? (anglais|français)", re.I),
    re.compile(r"^pourquoi ", re.I),
    re.compile(r"data-?set|objectif de mon travail|cents|100", re.I),
    re.compile(r"^pardon,", re.I),
    re.compile(r"je voulais dire", re.I),
    re.compile(r"animal", re.I),
    re.compile(r"temps il fait", re.I),
    re.compile(r"^joue l'émotion", re.I),
    re.compile(r"reconnais cette musique", re.I),
    re.compile(r"^ok, réfléchis", re.I),
    re.compile(r"qu'est-ce que tu parles", re.I),
    re.compile(r"tais-toi", re.I),
    re.compile(r"imagine demain", re.I),
    re.compile(r"semaine que j'ai passée.*mort vendredi", re.I),
    re.compile(r"ne t'entends pas", re.I),
    re.compile(r"collègue.*document", re.I),
    re.compile(r"^tu veux savoir ce que je fais", re.I),
    re.compile(r"parle tout le temps de toi", re.I),
    re.compile(r"réussi mon projet", re.I),
    re.compile(r"petit garçon", re.I),
    re.compile(r"^tu aimes la pluie", re.I),
    re.compile(r"surchauffes", re.I),
    re.compile(r"échanger tous les deux", re.I),
    re.compile(r"^tu es posé", re.I),
    re.compile(r"tu es tout calme", re.I),  # observation, pas ordre « zen »
    re.compile(r"^tu es sûr", re.I),  # question → chat sauf si annoté
]


def _infer_teacher(inp: str, original_teacher: str, seen: dict[str, int]) -> tuple[str, bool]:
    if inp in USER_ANNOTATIONS:
        return USER_ANNOTATIONS[inp]

    for pattern, teacher, also_chat in PATTERN_RULES:
        if not pattern.search(inp):
            continue
        if teacher == "KEEP":
            return original_teacher, False
        if teacher == "IRRITATED_PAIR":
            if seen.get(inp, 0) >= 1:
                return _emotion("displeased"), False
            return _emotion("irritated"), False
        return teacher, also_chat

    for pattern in FORCE_CHAT:
        if pattern.search(inp):
            return "chat", False

    if original_teacher.startswith("move_head:") and re.search(r"regarde(-moi)?[!.]?$", inp, re.I):
        return "head_tracking:on", False

    return original_teacher, False


def _parse_raw_line(line: str) -> tuple[dict[str, Any], str | None]:
    comment = None
    if "#" in line:
        json_part, comment_part = line.split("#", 1)
        comment = comment_part.strip()
    else:
        json_part = line
    return json.loads(json_part.strip()), comment


def _build_row(
    inp: str,
    teacher: str,
    also_chat: bool,
    ts: Any,
    original_teacher: str,
) -> dict[str, Any]:
    source_teacher = original_teacher if teacher != original_teacher else None
    return _build_trace_row(
        inp,
        teacher,
        ts=ts,
        also_chat=also_chat,
        source_teacher=source_teacher,
    )


def refine_teacher(
    inp: str,
    teacher: str,
    also_chat: bool,
    occurrence: int,
) -> tuple[str, bool]:
    """Affine les intents selon EMOTIONS_REFERENCE.md (prime sur inférence brute)."""
    exact: dict[str, tuple[str, bool]] = {
        "T'es méchant.": (_emotion("displeased"), False),
        "Tu es beau mon Richy.": (_emotion("loving"), False),
        "Tu sais aujourd'hui j'ai accompli beaucoup de choses.": (_emotion("success"), False),
        "Aujourd'hui, j'ai eu une longue journée avec mes collègues.": (_emotion("tired"), True),
        "J'ai marron.": (_emotion("irritated"), True),
        "J'en ai profondément marre de toi.": (_emotion("irritated"), True),
        "T'as de beaux yeux, tu sais.": (_emotion("loving"), False),
        "Tu as de beaux yeux, tu sais.": (_emotion("loving"), False),
        "Tu sais que t'es un petit robot trop mignon?": (_emotion("loving"), False),
        "Regarde ce fin cœur.": (_emotion("loving"), False),
        "Tu voudrais que je te présente Archie ?": (_emotion("excited"), False),
        "Oh, il se met à pleuvoir!": (_emotion("surprised"), False),
        "Fais de beaux rêves, je vais te débrancher.": (_emotion("goodbye"), True),
        "T'es tellement moche.": (_emotion("displeased"), True),
        "Fait le dégoût.": (_emotion("disgusted"), False),
        "Allez Richie, arrête de faire le timide et fais-moi un bisou.": (_emotion("loving"), False),
        "C'est hyper marrant.": (_emotion("happy"), False),
        "Tu es tout calme.": ("chat", False),
    }
    if inp in exact:
        return exact[inp]

    if inp == "Tu es insupportable.":
        if occurrence == 0:
            return _emotion("irritated"), False
        return _emotion("displeased"), False

    # downcast/lonely ne conviennent pas à l'exaspération (famille colère / mécontentement)
    lowered = inp.lower()
    if teacher in {_emotion("downcast"), _emotion("lonely")} and re.search(
        r"insupportable|marre|énerve|méchant|moche|déteste", lowered
    ):
        if "déteste" in lowered or "triste" in lowered:
            return _emotion("sad"), also_chat
        if "moche" in lowered or "méchant" in lowered:
            return _emotion("displeased"), also_chat
        return _emotion("irritated"), also_chat

    # grateful → loving pour compliments directs au robot
    if teacher == _emotion("grateful") and re.search(r"beau|mignon|t'aime|yeux|cœur", lowered):
        return _emotion("loving"), also_chat

    # longue journée / fatigue narrative
    if teacher == _emotion("surprised") and re.search(r"longue journée|fatigu", lowered):
        return _emotion("tired"), True

    # réussite / fierté
    if teacher == _emotion("amazed") and re.search(r"accompli|réussi|beaucoup de choses", lowered):
        return _emotion("success"), also_chat

    # au revoir / nuit
    if teacher == _emotion("sleepy") and re.search(r"débrancher|au revoir", lowered):
        return _emotion("goodbye"), True

    return teacher, also_chat


def curate() -> list[dict[str, Any]]:
    raw_lines = RAW_PATH.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []
    seen_inputs: dict[str, int] = {}

    for line in raw_lines:
        if not line.strip():
            continue
        record, comment = _parse_raw_line(line)
        inp = str(record["input"]).strip()
        if not inp or not _is_french_enough(inp):
            continue

        original_teacher = str(record.get("teacher", "chat"))

        if comment and "teacher" in comment.lower():
            teacher, also_chat = _parse_user_comment(comment)
        else:
            teacher, also_chat = _infer_teacher(inp, original_teacher, seen_inputs)

        occurrence = seen_inputs.get(inp, 0)
        teacher, also_chat = refine_teacher(inp, teacher, also_chat, occurrence)
        seen_inputs[inp] = occurrence + 1
        out.append(_build_row(inp, teacher, also_chat, record.get("ts"), original_teacher))

    return out


def main() -> None:
    curated = curate()
    OUT_PATH.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in curated),
        encoding="utf-8",
    )
    print(f"Wrote {len(curated)} lines to {OUT_PATH}")


if __name__ == "__main__":
    main()
