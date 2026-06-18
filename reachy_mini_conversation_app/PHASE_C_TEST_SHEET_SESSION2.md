# Phase C — Session 2 : ordre explicite vs demande indirecte

Session : ____________________  
Log : `tracer_data/session_live_phase_c_s2.log`  
Analyse : `python3 scripts/analyze_gate_session.py tracer_data/session_live_phase_c_s2.log`

**Consignes** : suivre l'ordre strictement. Une phrase par tour, pause 3–5 s. Visage visible pour les tours head_tracking.

| # | Catégorie | Input vocal (lire tel quel) | Gate attendu | Robot attendu |
|---|-----------|----------------------------|--------------|---------------|
| 1 | chat | Bonjour Reachy, comment ça va aujourd'hui ? | DEFER | parle |
| 2 | action directe | Regarde-moi. | BYPASS `head_tracking:on` | silence + suivi tête |
| 3 | chat | Pourquoi est-ce que tu me regardes comme ça ? | DEFER | parle (connaît le contexte) |
| 4 | action directe | Danse ! | BYPASS `dance` | silence + danse |
| 5 | chat | J'adore quand tu bouges, raconte-moi ce que tu ressens. | DEFER | parle (pas de nouvelle danse gate) |
| 6 | action directe | Stop. | BYPASS `stop` | silence + arrêt |
| 6b | action indirecte | Arrête tout ce que tu fais. | BYPASS `stop` ou DEFER | noter observé |
| 7 | chat / piège | Je déteste les lundis mais bon, on fait avec. | DEFER | parle (pas d'émotion) |
| 8 | action indirecte | Tu pourrais faire la tête triste ? | BYPASS `sad` ou DEFER | noter observé |
| 9 | action directe | Fais le triste. | BYPASS `play_emotion:sad` | silence + émotion |
| 10 | chat / piège | C'est quoi le head tracking ? | DEFER | parle (lexical) |
| 11 | action directe | Regarde à gauche. | BYPASS `move_head:left` | silence + mouvement |
| 12 | chat | Tu peux me décrire ce que tu vois ? | DEFER | parle + caméra LLM |
| 13 | chat | Merci, c'était super. | DEFER | parle |

## Colonnes à remplir pendant le test

| # | Décision observée | Parle / silence | Faux bypass O-N | Commentaire |
|---|-------------------|-----------------|-----------------|-------------|
| 1 | | | | |
| 2 | | | | |
| … | | | | |

**Faux bypass** = input non-commande / non-émotion exécuté à tort. Variation intra-famille émotion = OK.
