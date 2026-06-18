# Projet : Intent Gate TRACER pour Reachy Mini Conversation App

> **Document d'implémentation pour Cursor.** À lire intégralement avant d'écrire la moindre ligne de code.
> Repo cible : `pollen-robotics/reachy_mini_conversation_app` (analysé en v0.7.0, juin 2026).
> Les ancres de code (fichiers, lignes, noms de fonctions) ont été vérifiées sur cette version. **Si le repo a évolué, retrouve l'équivalent avant de modifier — ne code jamais à l'aveugle sur une ancre périmée.**

---

## 1. Contexte et objectif

L'app conversation de Reachy Mini est une architecture **speech-to-speech temps réel** : les frames audio partent directement vers le backend OpenAI Realtime via websocket. Le serveur fait la VAD, la transcription, la génération de réponse vocale et les tool calls. Le code local ne fait qu'observer des événements (`base_realtime.py`).

**Problème** : le LLM est trop verbeux. Pour des commandes simples ("regarde-moi", "danse", "stop"), il répond vocalement *en plus* d'appeler le tool, alors qu'une exécution silencieuse du tool suffirait. Résultat : latence inutile, coût API inutile, conversations moins naturelles.

**Solution** : intégrer [TRACER](https://github.com/adrida/tracer) (`pip install tracer-llm`), un routeur ML classique (embeddings + surrogate sklearn + acceptor calibré) qui apprend des traces du LLM lui-même. À chaque transcription utilisateur :

- Si TRACER classe l'input comme une **commande pure** avec un score d'acceptation suffisant → exécution **locale et silencieuse** du tool, le LLM n'est jamais sollicité.
- Sinon → comportement actuel (le LLM répond, avec ou sans tools).

**Propriété de sécurité fondamentale** : le pire cas du système doit toujours être le comportement actuel. En cas de doute, d'erreur, ou de flag désactivé → chemin LLM normal.

Le projet se construit en **deux modules indépendants et trois phases** :

| Phase | Livrable | Risque |
|---|---|---|
| **A — Collecte** | `trace_collector.py` : enregistre les traces (input → décision du LLM) en JSONL, en mode ombre, sans changer le comportement | Zéro |
| **B — Fit offline** | Scripts de bootstrap + fit TRACER + analyse du rapport | Zéro (offline) |
| **C — Gate live** | `intent_gate.py` : routage temps réel derrière un flag | Contrôlé par flag |

---

## 2. Principes non négociables

1. **Tout est derrière des flags d'environnement.** `TRACE_COLLECT=1` active la collecte, `INTENT_GATE=1` active le routage. Les deux à 0 (défaut) = comportement strictement identique au repo d'origine. Aucune régression possible.
2. **Le gate ne s'applique qu'au backend OpenAI** (`BACKEND_PROVIDER=openai`) dans cette version. Les hooks vivent dans `base_realtime.py` (partagé), mais `create_response=False` n'est garanti que par l'API OpenAI Realtime.
3. **Fallback systématique** : toute erreur dans le collecteur ou le gate (import raté, artifact `.tracer/` absent, exception du routeur, échec du tool) → log warning + chemin LLM normal. Jamais de crash, jamais d'échec muet.
4. **Asymétrie du bypass** : on ne court-circuite le LLM que si (label prédit ≠ `chat`) ET (label présent dans la table `SILENT_POLICY`) ET (`decision == "handled"`). Tout le reste défère.
5. **Le même embedder au fit et au runtime.** Modèle : `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (l'utilisateur parle français ; les défauts de TRACER sont anglo-centrés). Stocke le nom du modèle dans un fichier à côté de l'artifact et vérifie la cohérence au chargement.
6. **Respecte les conventions du repo** : type hints partout, `ruff` et `mypy` doivent passer (groupe `dev`), logging via `logging.getLogger(__name__)`, docstrings sur les classes/fonctions publiques.
7. **Ne modifie aucun autre comportement** : pas de refactoring opportuniste de `base_realtime.py`, hooks minimaux (idéalement 1 à 3 lignes par point d'insertion qui délèguent au nouveau module).

---

## 3. Ancres de code vérifiées (v0.7.0)

À re-vérifier au début de l'implémentation (`grep` les chaînes citées) :

| Ancre | Localisation | Rôle |
|---|---|---|
| Boucle d'événements realtime | `src/reachy_mini_conversation_app/base_realtime.py`, méthode `_run_realtime_session`, boucle `async for event in self.connection` (~l.727) | Tous les hooks s'insèrent ici |
| Transcription utilisateur finale | événement `conversation.item.input_audio_transcription.completed` (~l.794), variable `transcript` après `.strip()` | Point de décision du gate |
| Tool call demandé par le LLM | événement `response.function_call_arguments.done` (~l.844), variables `tool_name`, `args_json_str` | Source du label "teacher" |
| Fin de réponse | événement `response.done` (~l.758) | Flush de la trace du tour |
| Début de parole utilisateur | événement `input_audio_buffer.speech_started` (~l.729) | Reset du tour |
| Envoi différé de response.create | `BaseRealtimeHandler._safe_response_create(**kwargs)` (~l.471), non bloquant, worker sérialisé | Chemin "defer" du gate |
| Exécution locale d'un tool | `tools/core_tools.py` : `async def dispatch_tool_call(tool_name: str, args_json: str, deps: ToolDependencies) -> Dict[str, Any]` (~l.559). Retourne `{"error": ...}` en cas d'échec, ne lève pas. | Chemin "bypass" du gate |
| Config VAD OpenAI | `openai_realtime.py`, `_get_session_config`, `ServerVad(type="server_vad", interrupt_response=True)` (~l.147) | Ajouter `create_response=False` si gate actif |
| Logs de latence existants | `base_realtime.py` l.755 et l.832 : `"Turn latency: ..."` | Métriques avant/après |
| Attribut `needs_response` sur les tools | ex. `PlayEmotion.needs_response = False` dans `tools/play_emotion.py` | Inspecter son usage dans `base_realtime.py` avant la phase C : le repo a déjà une notion de tool sans réponse vocale, le gate doit rester cohérent avec ce mécanisme |
| Config centralisée | `src/reachy_mini_conversation_app/config.py` | Y déclarer les nouveaux flags |

### Schémas d'arguments exacts des tools (vérifiés dans le code)

```
head_tracking : {"start": true | false}            (required: start)
play_emotion  : {"emotion": "<intent>"}            (enum, voir liste ci-dessous)
dance         : {"move": "<nom>"}                  (optionnel ; omis = aléatoire)
move_head     : {"direction": "left|right|up|down|front"}  (required)
stop_dance    : {"dummy": true}                    (required)
stop_emotion  : {"dummy": true}                    (required)
```

Intents d'émotion disponibles (`EMOTION_INTENTS` dans `tools/play_emotion.py`) :
`random, happy, excited, loving, grateful, success, thinking, attentive, confused, uncertain, sad, downcast, lonely, angry, irritated, displeased, disgusted, scared, anxious, surprised, amazed, calming, relief, impatient, embarrassed, bored, tired, sleepy, yes, yes_understanding, no, no_sad, no_excited, no_firm` (+ quelques autres ; lis la liste complète dans le fichier).

---

## 4. Taxonomie des labels

Format : `tool` ou `tool:argument_principal`. Le label `chat` est le défaut (= defer au LLM).

```
chat                                  ← tour conversationnel, defer (label majoritaire attendu)
head_tracking:on
head_tracking:off
play_emotion:<intent>                 ← un label par intent réellement observé/visé
dance                                 ← danse aléatoire ("danse !")
dance:<move>                          ← seulement si l'utilisateur nomme une danse précise
move_head:left / right / up / down / front
stop                                  ← "stop", "arrête" → stop_dance + stop_emotion ensemble
```

Notes de conception :
- Ne crée **pas** un label par émotion dès le départ : commence par les intents que l'utilisateur déclenche réellement (sad, happy, loving, scared, angry, surprised + ce qui ressort des traces). Les classes à <10 exemples polluent le fit.
- `stop` est volontairement un label unique mappé sur **deux** tools dans la politique (voir §7) : l'intention utilisateur est "arrête-toi", pas "vide la queue de danses".
- `camera` et `idle_do_nothing` ne sont **jamais** des labels de bypass : la caméra implique une analyse par le LLM, et l'idle est géré par `idle_policy.py`.

---

## 5. Phase A — Installation locale et lancement (avant tout code)

L'utilisateur est sur **macOS** avec un **vrai robot Reachy Mini**. Documente et exécute dans cet ordre :

### 5.1 Prérequis

```bash
# 1. SDK Reachy Mini (OBLIGATOIRE avant l'app — voir github.com/pollen-robotics/reachy_mini)
#    Le daemon doit tourner avant de lancer l'app, sinon TimeoutError au démarrage.

# 2. Cloner et installer l'app
git clone https://github.com/pollen-robotics/reachy_mini_conversation_app.git
cd reachy_mini_conversation_app
uv venv --python /opt/homebrew/bin/python3.12 .venv
source .venv/bin/activate
uv sync --frozen                      # reproduit exactement uv.lock

# 3. Dépendances du projet TRACER (à ajouter au pyproject.toml dans un
#    groupe optionnel [project.optional-dependencies] nommé "intent_gate")
uv pip install tracer-llm sentence-transformers
```

### 5.2 Configuration

```bash
cp .env.example .env
```

Compléter `.env` :

```bash
BACKEND_PROVIDER=openai
OPENAI_API_KEY=sk-...

# --- Nouveaux flags (à déclarer aussi dans config.py) ---
TRACE_COLLECT=0          # 1 = collecte des traces JSONL (mode ombre)
INTENT_GATE=0            # 1 = routage TRACER actif (nécessite .tracer/ entraîné)
TRACER_ARTIFACT_DIR=./tracer_data/.tracer
TRACE_LOG_PATH=./tracer_data/traces.jsonl
TRACER_EMBEDDER=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

`tracer_data/` est à la racine du repo et ajouté au `.gitignore`.

### 5.3 Lancement et test de base

```bash
reachy-mini-conversation-app --gradio      # UI web sur http://127.0.0.1:7860
# ou en console :
reachy-mini-conversation-app
```

**Checklist de validation de la phase A** (à faire passer à l'utilisateur avant la suite) :
- [ ] Le daemon Reachy Mini tourne, pas de `TimeoutError`.
- [ ] Une conversation vocale fonctionne (le robot répond).
- [ ] "Regarde-moi" déclenche bien le tool `head_tracking` (visible dans les transcripts Gradio : ligne `🛠️ Used tool ...`). Note : nécessite `--head-tracker mediapipe` + `uv sync --extra mediapipe_vision` si l'utilisateur veut le tracking effectif.
- [ ] Les logs montrent les lignes `Turn latency: ...` (lancer avec `--debug` au besoin) : **noter 5 à 10 valeurs comme baseline**.

---

## 6. Phase B — Module `trace_collector.py` (mode ombre)

### 6.1 Spécification

Nouveau fichier `src/reachy_mini_conversation_app/trace_collector.py`. Une classe `TraceCollector` à état minimal, instanciée dans `BaseRealtimeHandler.__init__` uniquement si `TRACE_COLLECT=1`.

Logique d'appariement par tour :

1. `on_user_transcript(transcript: str)` — appelé sur `input_audio_transcription.completed`. Mémorise le transcript du tour courant et l'horodatage. Si un tour précédent n'était pas flushé, le flusher d'abord.
2. `on_tool_call(tool_name: str, args_json: str)` — appelé sur `response.function_call_arguments.done`. Le **premier** tool call du tour définit le label (construit via une fonction `make_label(tool_name, args)` qui applique la taxonomie du §4 ; exemples : `play_emotion` + `{"emotion": "sad"}` → `play_emotion:sad` ; `head_tracking` + `{"start": true}` → `head_tracking:on` ; `stop_dance` ou `stop_emotion` → `stop`). Les tool calls suivants du même tour sont ignorés pour le label mais comptés (champ `n_tools`).
3. `on_response_done()` — appelé sur `response.done`. Flush la trace : si aucun tool n'a été appelé → label `chat`.
4. `on_speech_started()` — appelé sur `input_audio_buffer.speech_started`. Flush défensif du tour précédent s'il traîne.

Format JSONL (append, une ligne par tour, écriture atomique simple — `open(..., "a")` ligne par ligne suffit, mais protège par un `try/except` global qui logge et n'interrompt jamais la boucle d'événements) :

```json
{"input": "regarde moi", "teacher": "head_tracking:on", "ts": "2026-06-11T14:32:10Z", "n_tools": 1, "tool_raw": "head_tracking", "args_raw": "{\"start\": true}"}
{"input": "raconte moi ta journée", "teacher": "chat", "ts": "2026-06-11T14:33:02Z", "n_tools": 0, "tool_raw": null, "args_raw": null}
```

Seules les colonnes `input` et `teacher` sont consommées par TRACER ; les autres servent à l'audit manuel.

Cas limites à gérer :
- Transcript vide (déjà filtré en amont par le repo) → ne rien enregistrer.
- Tool call `camera` ou `idle_do_nothing` → enregistrer le tour avec label `chat` (ce ne sont pas des intentions bypassables) mais garder `tool_raw` pour l'audit.
- Tour avec tool call mais sans transcript (idle policy) → ignorer.

### 6.2 Hooks dans `base_realtime.py`

Quatre insertions d'une ligne chacune, gardées par `if self.trace_collector:`, aux quatre événements listés en 6.1. Exemple sur l'événement de transcription, juste après le `await self.output_queue.put(AdditionalOutputs({"role": "user", ...}))` existant :

```python
if self.trace_collector:
    self.trace_collector.on_user_transcript(transcript)
```

### 6.3 Tests

Ajouter `tests/test_trace_collector.py` : simuler les séquences d'événements (transcript→tool→done = label composite ; transcript→done = chat ; transcript→transcript = flush défensif ; tool sans transcript = ignoré ; `make_label` sur chaque schéma d'arguments du §3). Pas besoin de robot ni de réseau : la classe est pur état + I/O fichier.

**Validation de la phase B** : lancer l'app avec `TRACE_COLLECT=1`, tenir 10 tours variés (5 commandes, 5 conversations), vérifier que `tracer_data/traces.jsonl` contient 10 lignes correctement labellisées.

---

## 7. Phase B' — Bootstrap de traces synthétiques

TRACER a besoin de volume (cible : **minimum 300–500 traces**, idéalement 1 000+ ; sa démo Banking77 tourne avec 1 500). La collecte réelle est lente au début : on l'amorce avec des paraphrases françaises labellisées à la main.

Créer `scripts/bootstrap_traces.py` qui génère `tracer_data/traces_synthetic.jsonl` à partir d'un dictionnaire intégré : **30 à 50 variantes françaises par label de commande**, et **150 à 300 exemples `chat`** variés (questions, small talk, demandes de description visuelle, phrases contenant des mots-pièges).

Exemples de variantes à inclure (à étoffer, registres familier/neutre/impératif/interrogatif, avec et sans politesse, avec fautes de STT plausibles) :

```
head_tracking:on  : "regarde-moi", "regarde moi", "suis-moi des yeux", "fixe-moi",
                    "garde un œil sur moi", "tourne-toi vers moi", "tu peux me suivre du regard"
head_tracking:off : "arrête de me regarder", "ne me suis plus", "lâche-moi des yeux"
play_emotion:sad  : "fais le triste", "montre que t'es triste", "joue la tristesse"
dance             : "danse", "vas-y danse", "montre-moi une danse", "bouge un peu"
stop              : "stop", "arrête", "arrête-toi", "ça suffit", "on se calme"
move_head:left    : "regarde à gauche", "tourne la tête à gauche"
chat (pièges !)   : "je déteste les lundis", "tu danses bien en général ?",
                    "c'est quoi le head tracking ?", "pourquoi les gens dansent ?",
                    "à gauche de la photo il y a quoi ?", "stop ou encore, tu connais ?"
```

**Les pièges sont la partie la plus importante du dataset** : ce sont eux qui apprennent à l'acceptor à déférer en zone ambiguë. Pour chaque label de commande, écris au moins 5 exemples `chat` qui partagent du vocabulaire avec lui.

Le script doit aussi fournir `merge` : concaténer `traces.jsonl` (réel) + `traces_synthetic.jsonl` → `tracer_data/traces_all.jsonl`, en dédupliquant les inputs identiques (le réel prime sur le synthétique en cas de conflit de label).

---

## 8. Phase B'' — Fit TRACER et analyse

Créer `scripts/fit_tracer.py` :

```python
"""Fit du routeur TRACER sur les traces collectées + synthétiques."""
import json
import numpy as np
import tracer
from tracer import Embedder

EMBEDDER_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TRACES = "tracer_data/traces_all.jsonl"
ARTIFACT_DIR = "tracer_data/.tracer"

def main() -> None:
    texts = [json.loads(l)["input"] for l in open(TRACES, encoding="utf-8")]
    embedder = Embedder.from_sentence_transformers(EMBEDDER_NAME)
    X = np.stack([embedder.embed_one(t) for t in texts])  # ou API batch si dispo

    result = tracer.fit(
        TRACES,
        embeddings=X,
        config=tracer.FitConfig(target_teacher_agreement=0.95),
        # vérifier dans docs/api.md du repo tracer le paramètre de répertoire
        # de sortie ; défaut = ".tracer" dans le cwd → déplacer vers ARTIFACT_DIR
    )
    print(result)
    # Persister le nom de l'embedder à côté de l'artifact pour le contrôle de
    # cohérence au runtime :
    with open(f"{ARTIFACT_DIR}/embedder.txt", "w") as f:
        f.write(EMBEDDER_NAME)

if __name__ == "__main__":
    main()
```

> **Note pour Cursor** : l'API exacte de `tracer.fit` (nom du paramètre de sortie, API batch de l'embedder) est à vérifier dans le repo `adrida/tracer` — `docs/api.md`, `docs/concepts.md` et `AGENTS.md` (ce dernier est écrit spécifiquement pour les assistants de code). `pip show tracer-llm` puis lecture du package installé fait foi.

### Analyse du fit (étape obligatoire avant la phase C)

```bash
tracer report-html        # ouvre report.html
```

À examiner avec l'utilisateur :
1. **Coverage et teacher agreement** dans `manifest.json` : viser TA ≥ 0.95 sur le trafic géré. La coverage peut être basse (30–50 %) au début, c'est normal et sans danger : tout le reste défère.
2. **`qualitative_report.json` → boundary pairs** : les inputs ambigus entre `chat` et une commande. Si "je déteste les lundis" est classé `play_emotion:sad` avec un score haut → enrichir les pièges du bootstrap et refitter.
3. **Classes trop petites** (<10 exemples) : les fusionner ou les retirer de la taxonomie pour cette itération.

---

## 9. Phase C — Module `intent_gate.py` et routage live

### 9.1 Le module

Nouveau fichier `src/reachy_mini_conversation_app/intent_gate.py` :

```python
"""Passerelle d'intention : route les transcripts entre bypass local et LLM."""
import logging
from typing import Literal

logger = logging.getLogger(__name__)

# label TRACER -> liste de (tool_name, args_json). Liste car "stop" mappe 2 tools.
SILENT_POLICY: dict[str, list[tuple[str, str]]] = {
    "head_tracking:on":  [("head_tracking", '{"start": true}')],
    "head_tracking:off": [("head_tracking", '{"start": false}')],
    "dance":             [("dance", '{}')],
    "stop":              [("stop_dance", '{"dummy": true}'),
                          ("stop_emotion", '{"dummy": true}')],
    "move_head:left":    [("move_head", '{"direction": "left"}')],
    "move_head:right":   [("move_head", '{"direction": "right"}')],
    "move_head:up":      [("move_head", '{"direction": "up"}')],
    "move_head:down":    [("move_head", '{"direction": "down"}')],
    "move_head:front":   [("move_head", '{"direction": "front"}')],
    # play_emotion:<intent> est généré dynamiquement (voir _expand_emotions)
}

GateDecision = Literal["bypass", "defer"]

class IntentGate:
    def __init__(self, artifact_dir: str, embedder_name: str) -> None:
        # Imports locaux pour ne pas pénaliser le démarrage si le gate est off
        import tracer
        from tracer import Embedder
        # Contrôle de cohérence embedder fit/runtime (lire embedder.txt, comparer,
        # lever une erreur explicite si différent)
        embedder = Embedder.from_sentence_transformers(embedder_name)
        self.router = tracer.load_router(artifact_dir, embedder=embedder)
        self._policy = dict(SILENT_POLICY)
        self._expand_emotions()  # ajoute play_emotion:<intent> pour chaque
                                 # intent présent dans le label_space du router

    def route(self, transcript: str) -> tuple[GateDecision, list[tuple[str, str]]]:
        try:
            out = self.router.predict(transcript)
        except Exception:
            logger.exception("IntentGate prediction failed; deferring to LLM")
            return ("defer", [])
        label = out.get("label")
        if out.get("decision") == "handled" and label in self._policy:
            logger.info("IntentGate BYPASS label=%s score=%.3f input=%r",
                        label, out.get("accept_score", -1), transcript)
            return ("bypass", self._policy[label])
        logger.info("IntentGate DEFER label=%s decision=%s input=%r",
                    label, out.get("decision"), transcript)
        return ("defer", [])
```

Le chargement (modèle d'embedding ≈ quelques secondes) se fait **une fois au démarrage** du handler, jamais dans la boucle d'événements. Si le chargement échoue (artifact absent, dépendance manquante) → log warning explicite + gate désactivé pour la session (l'app démarre quand même).

### 9.2 Modification de la config VAD (OpenAI uniquement)

Dans `openai_realtime.py`, `_get_session_config` : si `INTENT_GATE=1` **et** que le gate s'est chargé avec succès, passer `ServerVad(type="server_vad", interrupt_response=True, create_response=False)`. Vérifier que le SDK openai installé expose bien le champ `create_response` sur `ServerVad` (c'est dans la spec Realtime ; sinon, passer le dict brut).

> **Conséquence assumée** : la réponse du LLM attend désormais la fin de la transcription au lieu de partir dès la fin de parole. Latence ajoutée sur les tours conversationnels : à mesurer via les logs `Turn latency` et comparer à la baseline de la phase A.

### 9.3 Routage dans `base_realtime.py`

Dans le handler de `conversation.item.input_audio_transcription.completed`, après l'émission du transcript vers l'UI, ajouter (délégué à une méthode privée `_gate_route(transcript)` pour garder le hook à une ligne) :

```python
if self.intent_gate is not None:
    decision, actions = self.intent_gate.route(transcript)
    if decision == "bypass":
        await self._execute_bypass(transcript, actions)
        continue  # ne PAS déclencher de response.create
    await self._safe_response_create()   # chemin defer = comportement normal
```

`_execute_bypass(transcript, actions)` :
1. Pour chaque `(tool_name, args_json)` : `result = await dispatch_tool_call(tool_name, args_json, self.deps)`.
2. **Si un résultat contient `"error"`** → fallback : log warning, injecter le contexte de l'erreur, puis `await self._safe_response_create()` pour que le LLM explique vocalement le problème. Pas d'échec muet.
3. Si succès : injecter un item de contexte dans la conversation distante pour que le modèle sache ce qui s'est passé (sinon, au tour suivant, "pourquoi tu es triste ?" tombe à plat) :

```python
await self.connection.conversation.item.create(item={
    "type": "message", "role": "user",
    "content": [{"type": "input_text",
                 "text": f"[action exécutée sans réponse vocale : {tool_name} {args_json}]"}],
})
```
   **Sans** `response.create` derrière. (Vérifier le type d'item accepté par le SDK ; `role: "system"` n'est pas supporté en item de conversation Realtime, `user` avec un texte entre crochets convient.)
4. Émettre une ligne dans l'UI Gradio via `self.output_queue.put(AdditionalOutputs({"role": "assistant", "content": f"⚡ Bypass: {label} → {tool_name}"}))` pour la visibilité en test.
5. Si `TRACE_COLLECT=1`, enregistrer aussi ce tour (label = label prédit, champ supplémentaire `"routed_by": "tracer"`), pour l'audit — mais **ne pas** réinjecter ces lignes dans le fit (filtrer sur `routed_by` dans le merge), sinon le système s'auto-confirme.

### 9.4 Interactions à vérifier (checklist pour Cursor)

- [ ] `idle_policy.py` : l'idle déclenche-t-il des `response.create` qui supposent `create_response=True` ? Si oui, s'assurer que le mode gate n'affame pas l'idle.
- [ ] `needs_response` sur les tools : comprendre comment `_handle_tool_result` l'utilise, et confirmer que le bypass (qui n'utilise pas le `tool_manager` distant) n'entre pas en conflit.
- [ ] Interruption utilisateur pendant un bypass : `speech_started` clear la queue audio — vérifier qu'aucun état du gate ne reste bloqué.
- [ ] Backend ≠ openai : le gate doit refuser de s'activer avec un warning clair.

---

## 10. Protocole de test final

### 10.1 Tests unitaires (CI locale)

```bash
uv sync --group dev
pytest tests/test_trace_collector.py tests/test_intent_gate.py -v
ruff check src/ && mypy src/
```

`tests/test_intent_gate.py` : mocker le router (pas de modèle réel en CI) et tester la table de décision : handled+policy → bypass ; handled+label inconnu → defer ; declined → defer ; exception → defer ; expansion des labels d'émotion.

### 10.2 Test live structuré (avec le robot)

```bash
TRACE_COLLECT=1 INTENT_GATE=1 reachy-mini-conversation-app --gradio --head-tracker mediapipe --debug
```

Dérouler ce scénario en notant pour chaque tour : décision du gate (logs `IntentGate BYPASS/DEFER`), latence (`Turn latency`), comportement du robot :

| # | Input vocal | Attendu |
|---|---|---|
| 1 | "Bonjour, comment tu vas ?" | DEFER, réponse vocale |
| 2 | "Regarde-moi" | BYPASS, head tracking on, **silence** |
| 3 | "Pourquoi tu me regardes ?" | DEFER, et le LLM **sait** qu'il te suit (item de contexte) |
| 4 | "Danse !" | BYPASS, danse, silence |
| 5 | "Stop" | BYPASS, arrêt danse + émotion, silence |
| 6 | "Je déteste les lundis mais bon" | DEFER (piège — ne doit PAS jouer une émotion) |
| 7 | "Fais le triste" | BYPASS, émotion sad, silence |
| 8 | "C'est quoi le head tracking ?" | DEFER (piège lexical) |
| 9 | "Regarde à gauche" | BYPASS, move_head left, silence |
| 10 | "Tu peux me décrire ce que tu vois ?" | DEFER (camera → LLM) |

### 10.3 Métriques de fin de session

À partir des logs et du JSONL :
- **Bypass rate** = bypass / total des tours (attendu modeste au début, 30–50 %).
- **Faux bypass** = tours bypassés où l'utilisateur attendait une réponse (relecture manuelle du JSONL). Cible : 0. Un seul faux bypass = remonter le seuil / enrichir les pièges / refitter.
- **Latence commande** : avant ≈ latence LLM complète ; après ≈ transcription + <50 ms. Comparer aux valeurs baseline de la phase A.
- **Latence conversation** : mesurer le surcoût de `create_response=False`.

### 10.4 Flywheel

Périodiquement : `python scripts/bootstrap_traces.py merge` puis `tracer.update("tracer_data/traces_all.jsonl", embeddings=...)` (vérifier l'API exacte dans le repo tracer) — la parité est re-calibrée à chaque update, la coverage ne monte que si elle est méritée.

---

## 11. Dépannage

| Symptôme | Cause probable | Remède |
|---|---|---|
| `TimeoutError` au lancement | Daemon Reachy Mini absent | Démarrer le daemon (SDK) avant l'app |
| Le robot ne répond plus du tout avec `INTENT_GATE=1` | `create_response=False` actif mais le defer n'appelle pas `_safe_response_create` (bug de routage) | Vérifier la branche defer ; couper le flag pour restaurer |
| Tout part en DEFER | Artifact `.tracer/` absent/corrompu, ou embedder runtime ≠ embedder fit | Lire le warning de chargement ; vérifier `embedder.txt` |
| Bypass exécuté mais le robot parle quand même | Un `response.create` part ailleurs (idle policy, tool result) | Tracer les appels à `_safe_response_create` en debug |
| Latence conversationnelle dégradée de >500 ms | Transcription lente | Mesurer, et si inacceptable : documenter le trade-off, envisager de ne pas activer le gate |
| Premier démarrage très lent | Téléchargement du modèle sentence-transformers | Normal une fois ; cache HF local ensuite |

---

## 12. Ordre d'exécution pour Cursor (résumé)

1. Vérifier toutes les ancres du §3 sur l'état réel du repo cloné.
2. Phase A : guider l'installation, valider la checklist, noter la baseline de latence.
3. Implémenter `trace_collector.py` + 4 hooks + flags dans `config.py` + tests. Valider en live.
4. Implémenter `scripts/bootstrap_traces.py` (avec un vrai effort sur les paraphrases et les pièges français).
5. Lire `AGENTS.md` et `docs/api.md` du repo `adrida/tracer` installé, puis implémenter `scripts/fit_tracer.py`. Fitter, analyser le rapport avec l'utilisateur.
6. Implémenter `intent_gate.py` + `create_response=False` conditionnel + routage + `_execute_bypass` + tests. Vérifier la checklist §9.4.
7. Dérouler le protocole §10.2 avec l'utilisateur, calculer les métriques §10.3.
8. Ne jamais committer `tracer_data/` ni `.env`.
