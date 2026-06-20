# Phase « Re-constitution du dataset » — Outil d'annotation humaine + re-fit

> Document d'implémentation pour Cursor. Objectif : remplacer un dataset trop synthétique par un dataset majoritairement **humain et authentique**, grâce à un petit outil d'annotation rapide, puis refaire le fit (B'') et la validation live (V).
> À lire en entier. Démarre en **mode plan** : présente le plan, attends validation, puis implémente.

---

## 1. Contexte et objectif

Le routeur actuel fonctionne mais a été entraîné sur ~1469 traces synthétiques pour ~119 réelles. Conséquence : il est fidèle à des formulations **artificielles**, et réagit moins bien aux phrases humaines spontanées. La correction n'est pas algorithmique, elle est **dans les données** : il faut davantage de vraies traces, annotées par un humain.

Le goulot d'étranglement, c'est la vitesse d'annotation. D'où cet outil : une petite interface locale qui présente chaque trace (input réel + label proposé par le LLM) et permet, en un clic, de **valider / corriger / supprimer**. À la fin, on sauvegarde l'original et la version annotée remplace `traces.jsonl` en place, puis on refait le fit et on revalide.

**Vocabulaire à clarifier** (l'utilisateur dit « tracer.json ») : les traces sont dans des fichiers **JSONL** (`tracer_data/traces*.jsonl`), une ligne JSON par trace `{"input": ..., "teacher": ...}`. L'artefact entraîné est le dossier séparé `tracer_data/.tracer/`. L'annotation porte sur les **JSONL** ; le `.tracer/` est régénéré ensuite par le fit.

---

## 2. Modèle de données : réécriture en place avec backup

Flux simple, conforme à la demande utilisateur :

- **Pendant l'annotation**, les décisions (valider / corriger / supprimer) sont tenues en mémoire par le serveur, et persistées dans un petit fichier de travail temporaire `tracer_data/.annotation_session.jsonl` (pour ne rien perdre si on ferme l'onglet en cours de route). Ce fichier est interne à l'outil, pas destiné au fit.
- **À la finalisation** (bouton « Finaliser » dans l'UI, ou endpoint dédié), l'app :
  1. **Sauvegarde l'original** : copie horodatée du fichier de traces, ex. `tracer_data/traces.jsonl.bak-YYYYMMDD-HHMMSS` (jamais écrasée — une par finalisation). Filet de sécurité en cas de regret.
  2. **Réécrit le fichier de traces en place** (`tracer_data/traces.jsonl`) avec la version annotée : lignes validées gardées telles quelles, lignes corrigées avec leur nouveau `teacher`, lignes supprimées retirées.
  3. **Aucune mention de correction** dans le fichier final : chaque ligne reste `{"input": ..., "teacher": ...}` (+ les champs déjà présents type `ts`), exactement la forme attendue par TRACER. Pas de `reviewed`, pas de `original_teacher`, pas de commentaire `#` — le fichier reste un JSONL propre directement consommable par le fit.
  4. Supprime le fichier de travail `.annotation_session.jsonl`.

> En clair : on ne fabrique pas de fichier « curé » à côté. La version annotée **devient** le `traces.jsonl`, l'original est juste mis de côté en `.bak` au cas où. Si une finalisation tourne mal, on restaure le `.bak`.

**Concurrence** : ne pas lancer une session robot (`TRACE_COLLECT=1` qui appende dans `traces.jsonl`) en même temps qu'une finalisation, puisque la finalisation réécrit ce fichier. L'outil d'annotation se lance sur un dataset figé ; si tu veux annoter du live, fais-le en deux temps (collecter, arrêter la collecte, puis annoter/finaliser).

### Identifiant de ligne (interne à la session)

Pour relier une décision à sa ligne, l'outil indexe les traces par **position de ligne** dans le fichier chargé (numéro de ligne), ou par `id` si déjà présent. Pas besoin d'`id` persistant : la session d'annotation travaille sur un snapshot du fichier chargé au démarrage, et la finalisation réécrit ce même snapshot avec les décisions appliquées. Si le fichier contient déjà un `id`, le conserver ; sinon, ne pas en ajouter (rester sur la forme minimale).

---

## 3. L'outil d'annotation

### 3.1 Stack (un seul fichier, lançable depuis Cursor, affichage HTML)

Contrainte : l'outil doit pouvoir être **lancé directement depuis Cursor** (un bouton « run » sur un fichier Python) et s'**afficher en HTML** dans le navigateur, sans build, sans dépendance lourde, sans étape de setup.

**Solution retenue : un seul fichier Python autonome, zéro dépendance externe.**
- Backend : `http.server` de la **stdlib** (aucune install : ni FastAPI, ni uvicorn, ni npm).
- Frontend : la page **HTML/CSS/JS vanilla est embarquée en chaîne dans le même fichier Python** et servie à la racine `/`.
- Données : lit/écrit les JSONL directement (voir §2).
- Lancement : `python scripts/annotate.py` → démarre le serveur sur `http://127.0.0.1:8000` et **ouvre le navigateur** automatiquement (`webbrowser.open`). Depuis Cursor : ouvrir `scripts/annotate.py` et cliquer Run, ou lancer la commande dans le terminal intégré.

Un seul fichier `scripts/annotate.py` contient donc : le handler HTTP (routes API + service de la page), le HTML embarqué, la génération de la palette, la logique de finalisation (backup + réécriture), et le `main()` qui démarre le serveur. Pas d'arborescence `annotation/`, pas de `static/` séparé — tout est dans ce fichier pour rester trivial à lancer et à déplacer.

> Pourquoi pas FastAPI/Gradio : ils ajoutent des dépendances et une couche de setup. Ici on veut « ouvrir un fichier, cliquer run, annoter ». La stdlib suffit largement pour un outil local mono-utilisateur. La finalisation (backup + réécriture en place, §4) est gérée par ce même fichier, via un endpoint dédié.

Endpoints servis par le handler stdlib (mêmes contrats qu'en §3.4) : `GET /`, `GET /api/labels`, `GET /api/queue`, `GET /api/preview`, `POST /api/annotate`, `POST /api/finalize`, `GET /api/stats`. Le polling côté JS (toutes ~1–2 s) gère le temps réel et la file.

### 3.3 Flux temps réel + file d'attente

Au démarrage, le serveur **charge un snapshot de `traces.jsonl`** : toutes les lignes non encore traitées dans la session entrent dans la **file**. La file affiche **une trace à la fois** (la plus ancienne non traitée), avec un compteur « N en attente ». Les décisions prises sont mémorisées dans le fichier de travail de session (§2), de sorte qu'on peut fermer et rouvrir l'onglet sans perdre l'avancement. Le polling JS (~1–2 s) sert juste à rafraîchir le compteur et la trace courante.

### 3.4 Endpoints

```
GET  /                      -> static/index.html
GET  /api/labels            -> structure de la palette (groupes -> labels)
GET  /api/queue?limit=20    -> [{id, input, llm_teacher, ts, also_chat, also_head_tracking}, ...]
GET  /api/preview           -> ?teacher=&also_chat=&also_head_tracking= → preview Phase 2
POST /api/annotate          -> body {line_id, action, teacher?, also_chat?, also_head_tracking?}
POST /api/finalize          -> backup + réécriture en place de traces.jsonl (voir §4)
GET  /api/stats             -> {total, reviewed, remaining, by_action:{validate,correct,delete}, top_labels:[{label,count}, ...]}
```

`llm_teacher` = le champ `teacher` original de la trace (la décision du LLM), affiché pour que l'humain valide ou corrige. `top_labels` = classement des labels assignés dans la session (validés + corrigés), pour alimenter le Top 4 des flèches (§3.5).

### 3.5 L'interface (index.html)

Affichage d'une trace :
- L'**input** en grand (la phrase transcrite réelle).
- Le **label proposé par le LLM** (`llm_teacher`), bien visible.
- Trois actions principales :
  - **Valider** → `POST {action:"validate"}` : la trace est gardée telle quelle (teacher du LLM accepté comme vérité).
  - **Supprimer** → `POST {action:"delete"}` : la trace sera retirée du fichier à la finalisation (transcript poubelle, doublon, etc.).
  - **Corriger** → révèle la **palette de labels** (voir 3.6). Après sélection → `POST {action:"correct", teacher:"<label choisi>"}`.

#### Accès rapide « Top 4 » avec les flèches du clavier

Pour accélérer la correction vers les labels les plus fréquents :
- **Calcul en live** : l'outil maintient un compteur des labels effectivement assignés au cours de la session (les `teacher` validés + corrigés). Le **Top 4 des labels les plus utilisés** est affiché en évidence, au-dessus de la palette complète, sous forme de 4 grands boutons.
- **Raccourcis flèches** : les 4 flèches du clavier mappent ces 4 boutons — `←` Top 1, `↑` Top 2, `→` Top 3, `↓` Top 4 (ou un mapping clair affiché sur chaque bouton). Appuyer sur une flèche applique directement la correction vers ce label **et passe à la trace suivante**, sans ouvrir la palette complète.
- **Mise à jour dynamique** : le Top 4 se recalcule au fil de l'annotation ; l'ordre et le contenu des 4 boutons évoluent avec tes habitudes de la session. Afficher le petit compteur d'usage à côté de chaque label (ex. `dance ·12`) pour que tu voies pourquoi il est là.
- **Amorçage** : au démarrage de session (compteur vide), initialiser le Top 4 avec les 4 labels les plus fréquents du fichier `traces.jsonl` chargé (d'après le champ `teacher` existant), pour que les flèches soient utiles dès la première trace.
- **Repli** : si moins de 4 labels distincts ont été vus, compléter avec les labels de commande les plus courants (`chat`, `head_tracking:on`, `dance`, `stop`) pour que les 4 flèches soient toujours actives.
- Chaque bouton Top 4 affiche le label en clair + la flèche associée, pour rester lisible sans mémoriser le mapping.

Autres raccourcis clavier (inchangés, complémentaires des flèches) :
- `V` valider, `D` supprimer, `C` ouvrir la palette complète (pour les labels hors Top 4), `Entrée` confirmer une correction depuis la palette.
- Après chaque action (flèche, V, D, ou correction via palette), passer automatiquement à la trace suivante.

Affichage complémentaire : un compteur « N en attente » et un petit fil des dernières décisions (avec possibilité d'annuler la dernière).

### 3.6 La palette de correction — modèle à deux niveaux

L'utilisateur a parlé de « cliquer sur un ou plusieurs tools ». Précision technique importante : **TRACER est un classifieur à label unique** — le champ `teacher` est **une** chaîne. La palette doit donc produire un label valide de la taxonomie, pas un tool brut.

Palette organisée par familles (boutons), générée depuis les schémas de tools (`labels.py`) :

- **Conversation** : `chat` (bouton mis en avant — beaucoup de corrections seront « en fait c'est juste de la conversation »).
- **head_tracking** → sous-boutons `on` / `off` → label `head_tracking:on|off`.
- **move_head** → `left` / `right` / `up` / `down` / `front` → `move_head:<dir>`.
- **dance** → `dance` (+ moves nommés si pertinents) → `dance` ou `dance:<move>`.
- **stop** → `stop`.
- **play_emotion** → l'émotion choisie → `play_emotion:<intent>`. Comme la liste `EMOTION_INTENTS` est longue (~35), **regrouper visuellement** pour scanner vite :
  - Positives : happy, excited, loving, grateful, success, amazed, relief, calming, surprised
  - Négatives : sad, downcast, lonely, angry, irritated, displeased, disgusted, scared, anxious, embarrassed, impatient, bored
  - Cognitives/neutres : thinking, attentive, confused, uncertain, tired, sleepy
  - Sociales/réponses : greeting, goodbye, welcoming, yes, yes_understanding, no, no_sad, no_excited, no_firm
  (utiliser la liste réelle de `EMOTION_INTENTS` dans `tools/play_emotion.py` comme source de vérité).

**Sélection simple par défaut** (un label = un clic → un `teacher`). C'est le cas dans ~99 % des corrections.

> **Ne pas utiliser de labels composites `+`** (ex. `dance+play_emotion:happy`). TRACER reste un classifieur à **label unique**. Pour combiner une action avec de la voix ou le regard, utiliser les flags d'annotation enrichie (§3.7).

### 3.7 Annotation enrichie Phase 1 (`also_*`)

Phase 1 ajoute deux flags **indépendants**, conservés dans le JSONL à la finalisation mais **hors fit TRACER** :

| Champ | Signification | Exemple |
|-------|---------------|---------|
| `teacher` | Label unique TRACER | `play_emotion:surprised` |
| `also_chat` | Émotion + réponse vocale (hybrid Phase 2) | `true` |
| `also_head_tracking` | Action + regard (enrichment Phase 2) | `true` |

**UI (`scripts/annotate.py`) :**
- Case **Regard** (`also_head_tracking`) — indépendante de `also_chat`
- Case **Parler aussi** (`also_chat`)
- Raccourci **Émotion + parler** : émotion + `also_chat` coché
- **Preview Phase 2** (lecture seule) : simule le runtime futur, ex. `[head_tracking:on → play_emotion:surprised]` ou `[hybrid: play_emotion:irritated + voix]`
- Endpoint `GET /api/preview?teacher=...&also_chat=...&also_head_tracking=...`

**Exemples JSONL alignés sur les scénarios de référence** (voir [GATE_POLICY_PHASE2.md](GATE_POLICY_PHASE2.md)) :

```json
{"input": "Boo ! Je t'ai fait peur ?", "teacher": "play_emotion:surprised", "also_head_tracking": true}
{"input": "J'ai marron.", "teacher": "play_emotion:irritated", "also_chat": true}
{"input": "Raconte-moi une blague.", "teacher": "chat"}
{"input": "Regarde-moi.", "teacher": "head_tracking:on"}
```

**Pipeline policy** : annoter → `python3 scripts/derive_gate_policy.py` → revue humaine du snippet → intégration Phase 2 dans `intent_gate.py`. Aucune règle hardcodée (ex. surprise→regard) : la récurrence humaine alimente la policy.

---

## 4. Finalisation : ce que fait l'app au moment d'écrire

Il n'y a **pas de script de build séparé**. La finalisation (déclenchée depuis l'UI) applique les décisions de la session et réécrit `traces.jsonl` en place, après backup. Logique :

1. Backup horodaté de `traces.jsonl` → `traces.jsonl.bak-<timestamp>` (jamais écrasé).
2. Construire la version annotée en mémoire : valider = ligne inchangée ; corriger = `teacher` remplacé ; supprimer = ligne retirée.
3. **Valider la conformité** avant d'écrire (voir §4 bis). Si une ligne est non conforme → **abandonner la finalisation sans toucher au fichier** (l'original reste intact, le backup aussi) et afficher l'erreur.
4. Écrire le fichier `traces.jsonl` (JSONL propre, forme minimale `{"input", "teacher"}` + champs déjà présents). Aucune métadonnée de correction.
5. Nettoyer le fichier de travail de session.
6. Afficher un récap : n validées / corrigées / supprimées, chemin du backup créé.

### 4 bis. Conformité au format attendu par TRACER (garde-fou avant écriture)

Le fichier réécrit doit rester directement consommable par `tracer.fit`. Avant d'écrire (étape 3 ci-dessus), vérifier chaque ligne :
- JSON valide, UTF-8, une ligne = un objet, pas de ligne vide, pas de commentaire `#`.
- `input` : chaîne non vide. `teacher` : **une seule chaîne** (jamais une liste), appartenant à la taxonomie (`chat`, `head_tracking:on|off`, `move_head:<dir>`, `dance`/`dance:<move>`, `stop`, `play_emotion:<intent>`).
- Conserver les champs déjà présents (`ts`, `also_chat`, `also_head_tracking`, etc.) ; ne pas ajouter de champs de provenance d'annotation.

Cursar sait configurer TRACER, mais **vérifier d'abord (cf. §6 bis) que la version installée attend bien les clés `input`/`teacher`** et pas d'autres noms. Si elles ont changé, c'est l'écriture qui s'aligne sur la forme attendue. En cas de doute, faire un test de fumée : recharger le fichier réécrit avec le loader réel de TRACER sur quelques lignes.

---

## 5. Reboucler : constitution → bootstrap léger → B'' → V

L'objectif qualité guide les proportions. **Cible : traces réelles ≥ 80 %, synthétiques ≤ 20 %** (l'inverse de la situation actuelle).

1. **Constitution (réel)** : collecter de vraies traces (`TRACE_COLLECT=1`, sessions robot variées et spontanées) puis les annoter avec l'outil. Viser le plus grand volume réel possible.
2. **Bootstrap léger (+15–20 %)** : `bootstrap_traces.py` ne sert plus qu'à **combler les trous** — labels rares peu représentés dans le réel, et surtout les **pièges** (`chat` partageant du vocabulaire avec des commandes). Ne PAS regénérer un gros volume synthétique. Adapter le script pour plafonner la part synthétique à ~20 % du total.
3. **Merge** : `traces.jsonl` (réel annoté) + `traces_synthetic.jsonl` (léger) → `traces_all.jsonl`, en dédupliquant (réel prioritaire sur synthétique).
4. **B'' — re-fit** : `scripts/fit_tracer.py --reuse-embeddings` si possible (cache), même embedder multilingue, `target_teacher_agreement=0.95`. Exclure `gbt` du sweep (déjà fait). Lire le rapport : TA, coverage, boundary pairs, et **vérifier que les pièges tombent du bon côté**.
5. **V — re-validation live** : redérouler le protocole des 10 tours (§10.2 de la spec), gate `INTENT_GATE=1`, et surtout tester avec des **phrases spontanées** (pas les formulations du bootstrap) puisque c'est précisément ce qu'on cherche à améliorer. Auditer les faux bypass (définition raffinée : variation intra-famille = OK).

---

## 6. Garde-fous

- **Outil dev-only** : un seul fichier `scripts/annotate.py`, **aucune dépendance externe** (stdlib uniquement). `tracer_data/`, les `.bak-*` et `.env` jamais commités.
- **Backup avant toute écriture** : la finalisation crée un `.bak-<timestamp>` avant de réécrire `traces.jsonl` ; en cas de souci, on restaure le backup.
- **Validation avant écriture** : une ligne non conforme annule la finalisation sans toucher au fichier (§4 bis).
- **Pas de commentaires dans les JSONL** : provenance via champs (`reviewed`, `original_teacher`), jamais via `#`.
- **Label unique** : pas de composites `+` ; combinaisons via flags `also_*` (§3.7).
- **Pas de collecte live pendant la finalisation** : ne pas faire tourner une session robot qui appende dans `traces.jsonl` pendant qu'on finalise (la finalisation réécrit ce fichier).
- **Ne pas toucher** au `intent_gate.py`, au seuil calibré de TRACER, ni à la `SILENT_POLICY` dans cette phase : on ne change que les données et le pipeline d'annotation.

---

## 6 bis. Vérification préalable OBLIGATOIRE : version de TRACER

Avant tout code, **inspecte la version installée de TRACER et compare-la à la dernière publiée**. Notre intégration (fit, `load_router`, `predict`, format de l'artefact, embedder) a été écrite contre une version antérieure ; une montée de version peut avoir changé l'API, le format de l'artefact `.tracer/`, ou ajouté des fonctionnalités utiles à ce projet.

Étapes à mener et à **rapporter dans le plan** :

1. **Version installée** : `pip show tracer-llm` (numéro + emplacement). Lire le code réellement installé, pas la mémoire.
2. **Dernière version publiée** : vérifier sur PyPI (`tracer-llm`) et le dépôt `adrida/tracer` (releases, CHANGELOG, commits récents, `AGENTS.md`, `docs/`). Noter l'écart de version.
3. **Diff fonctionnel ciblé** — pour chaque point ci-dessous, dire « inchangé » ou « changé + nature » :
   - Signature de `tracer.fit(...)` et de `FitConfig` (noms de paramètres, répertoire de sortie, `target_teacher_agreement`, exclusion de candidats type `gbt`).
   - API runtime : `tracer.load_router(...)`, `router.predict(...)` — clés du dict retourné (`label`, `decision`, `accept_score` : toujours présentes ? renommées ?). **Notre `intent_gate.route()` en dépend directement.**
   - `Embedder.from_sentence_transformers(...)` et l'API d'embedding (batch vs `embed_one`).
   - Format/chemins de l'artefact `.tracer/` (`pipeline.joblib`, `index/`, `manifest.json`, `qualitative_report.json`) et compatibilité de l'artefact déjà entraîné.
   - `tracer.update(...)` (flywheel) : signature et comportement.
   - Nouveautés pertinentes : meilleurs embedders multilingues supportés, nouvelles métriques de rapport, API d'annotation/active-learning éventuelle, format d'export.
4. **Compatibilité de l'artefact existant** : déterminer si le `tracer_data/.tracer/` actuel reste chargeable avec la nouvelle version, ou s'il faut **re-fitter** (de toute façon prévu en B'').

**Règles de décision :**
- Si une montée de version **améliore** le projet sans casse (meilleur embedder multilingue, métriques de rapport plus fines, API d'annotation native) → proposer la mise à jour dans le plan, en listant les fichiers impactés (`fit_tracer.py`, `intent_gate.py`, `requirements`/`pyproject`).
- Si la nouvelle version **change l'API consommée par `intent_gate.route()`** (clés du dict de `predict`) → c'est prioritaire : adapter `route()` et ses tests, sinon le gate casse silencieusement.
- Si une nouveauté **recoupe l'outil d'annotation** qu'on s'apprête à construire (active learning, boucle de correction, UI de revue intégrée) → **le signaler avant de coder** : inutile de réimplémenter ce que TRACER fournirait nativement. Présenter l'arbitrage (réutiliser le natif vs garder notre outil sur-mesure).
- Si rien de pertinent n'a changé → le dire explicitement et continuer sur l'API actuelle.

Ne fige aucune version « au hasard » : épingle la version retenue dans `pyproject.toml` et note dans le plan pourquoi (stabilité vs nouveauté).

---

## 7. Démarrage en mode plan (à produire avant tout code)

Présente un plan qui :
1. **Inspecte la version de TRACER (§6 bis)** : version installée vs dernière publiée, diff fonctionnel ciblé, compatibilité de l'artefact, et recommandation (mettre à jour ou non, avec impact). **C'est le tout premier point du plan.**
2. Re-vérifie l'état réel : nom/chemin du fichier de traces réel actuel (`traces.jsonl` ?), format exact des lignes déjà écrites par `trace_collector.py`, présence ou non d'un `id`.
3. Liste les fichiers créés/modifiés (`scripts/annotate.py` unique avec serveur + HTML + finalisation, plafond synthétique dans `bootstrap_traces.py`, + tout fichier impacté par une montée de version TRACER).
4. Détaille la palette générée depuis `EMOTION_INTENTS` réel + schémas de tools (montre la structure de `/api/labels`).
5. Confirme le flux backup + réécriture en place (§2 et §4) **et le contrat de format dérivé du TRACER installé (§4 bis) : noms de champs exacts, `teacher` chaîne unique, validation avant écriture**.
6. Intègre la cible de proportion réel ≥ 80 % / synthétique ≤ 20 % dans l'étape bootstrap.
7. Se termine par la boucle B'' + V comme critère de fin.

Attends la validation du plan avant d'écrire le code.

---

## 8. Ordre d'implémentation recommandé

0. **Inspecter la version de TRACER (§6 bis)** : diff installée vs dernière, décider mise à jour ou non, adapter `fit_tracer.py` / `intent_gate.route()` / `pyproject.toml` si l'API a changé, et signaler toute nouveauté recoupant l'outil d'annotation **avant** de coder celui-ci.
1. `scripts/annotate.py` — **fichier unique autonome** : handler stdlib `http.server`, HTML embarqué, palette générée depuis `EMOTION_INTENTS` + schémas de tools, endpoints (`/`, `/api/labels`, `/api/queue`, `/api/annotate`, `/api/finalize`, `/api/stats`), `main()` qui démarre le serveur et ouvre le navigateur. Lançable d'un clic Run depuis Cursor.
3. UI dans le HTML embarqué : 3 actions (valider/supprimer/corriger), **Top 4 des labels en live mappé sur les flèches `← ↑ → ↓` (§3.5, recalculé à chaque décision, amorcé depuis le fichier chargé)**, palette à deux niveaux pour les labels hors Top 4, raccourcis `V`/`D`/`C`/`Entrée`, compteur « N en attente », annuler-dernier.
4. Finalisation dans `annotate.py` : backup `.bak-<timestamp>` + réécriture en place de `traces.jsonl`, avec **validation de conformité bloquante avant écriture (§4 bis)**.
5. Plafond synthétique ≤ 20 % dans `bootstrap_traces.py` + merge dédupliqué.
6. Tests : la finalisation applique correctement valider/corriger/supprimer ; le fichier réécrit est conforme (forme `{input, teacher}`, label dans la taxonomie, pas de commentaire) ; le backup est bien créé avant écriture.
7. Boucle : collecte réelle → annotation → build → fit (B'') → validation live (V).
