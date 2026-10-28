# Grok MCP Bridge v3

Bridge de production reliant **Claude ↔ Grok (xAI)**, déployé sur Railway.

## Pourquoi ce bridge ?

Claude est excellent pour raisonner et structurer. Grok apporte la **recherche web et X en temps réel**, une **critique directe sans filtre**, et une forte capacité sur le code. Ce bridge donne accès aux deux depuis un seul point d'entrée MCP — avec le contexte métier Taranis Cooperage injecté automatiquement à chaque appel.

---

## Point d'entrée : `grok_dispatch`

Plus de routage par mots-clés : l'appelant choisit le `mode`.

```
grok_dispatch(prompt="Prix marché des fûts bourbon en Écosse", mode="research")
grok_dispatch(prompt="Critique ce plan commercial Japon", mode="critique", effort="high")
grok_dispatch(prompt="Corrige cette erreur : TypeError...", mode="code")
grok_dispatch(prompt="Qu'est-ce qu'un fût STR ?")           # mode general par défaut
```

`task` (ancien nom) reste accepté : `review`, `code_test`, `search`, `market`… sont traduits.

---

## Architecture

```
main.py                          ← Serveur FastMCP + enregistrement des tools
├── auth.py                      ← Garde Bearer optionnelle (MCP_BEARER_TOKEN)
├── grok_client.py               ← Client unique Grok (Responses API, profils d'effort, coût)
├── llm_clients.py               ← grok_chat (debate) + claude_chat (Anthropic)
├── orchestration.py             ← verify, cross_check, débat
├── router/router.py             ← Validation du mode de grok_dispatch
├── tools/                       ← Un fichier par tool MCP
└── context/taranis_context.md   ← Contexte métier injecté (vocabulaire maison compris)
```

---

## Tools disponibles

| Tool | Quand l'appeler directement |
|------|-----------------------------|
| `grok_dispatch` | Point d'entrée principal, avec `mode` |
| `grok_critique` | Revue approfondie avec `focus=` précis (ex: "risque Corée") |
| `grok_code_test` | Debug itératif avec `session_id` + `error_message` |
| `grok_research` | Recherche web + X en direct (`sources="web" | "x" | "web+x"`), sources citées |
| `grok_verify` | Recherche Grok **puis contrôle par Claude** de chaque chiffre (✅ / ⚠️ / ❌) — quand les chiffres vont servir |
| `grok_cross_check` | Même question à Grok et Claude en parallèle, puis comparaison par un arbitre (`judge`) |
| `grok_debate` | Débat : tours en parallèle, arrêt dès accord, synthèse par l'arbitre (`judge`, `turns` 1-4) |
| `grok_x_pulse` | Ce qui se dit sur X d'une marque / d'un sujet (`days`, `handles`) |
| `grok_structured` | Réponse JSON conforme à un JSON Schema → `{data, meta}` |
| `ask_claude`, `save_project_note`, `get_project_notes` | Mémoire de projet partagée |

Tous les tools Grok acceptent `effort` et `model` :

| effort | Modèle | Raisonnement | Budget sortie | Recherches max | Timeout |
|---|---|---|---|---|---|
| `low` | grok-4.20-0309-non-reasoning | — | 1 500 | 2 tours | 45 s |
| `medium` (défaut) | grok-4.7 | low | 4 000 | 3 tours | 90 s |
| `high` (défaut de `grok_code_test`) | grok-4.7 | high | 8 000 | 6 tours | 180 s |
| `max` | grok-4.7 | xhigh | 16 000 | 10 tours | 300 s |

`model="grok-4.6"` force un modèle précis. Chaque réponse se termine par une ligne `modèle · effort · tokens · outils · ≈ coût $` (estimation, pas la facture xAI).

---

## Installation

```bash
cp .env.example .env      # Remplir XAI_API_KEY
pip install -r requirements.txt
python main.py
```

Variables clés dans `.env` :

| Variable | Défaut | |
|----------|--------|-|
| `XAI_API_KEY` | — | **Obligatoire** |
| `GROK_MODEL_MAIN` | `grok-4.7` | Modèle des profils medium / high / max |
| `GROK_MODEL_LOW` | `grok-4.20-0309-non-reasoning` | Modèle du profil low (et du debate) |
| `GROK_DEFAULT_EFFORT` | `medium` | Effort quand l'appelant n'en donne pas |
| `GROK_EFFORT_MODELS` | `grok-4.7,grok-4.6,grok-4.5` | Modèles qui reçoivent `reasoning.effort` |
| `PORT` | `8000` | Fixé automatiquement par Railway |
| `MCP_BEARER_TOKEN` | — | Si défini, `/mcp` exige `Authorization: Bearer <token>` (401 sinon). Absent = ouvert, warning au boot |
| `TARANIS_CONTEXT_PATH` | `context/taranis_context.md` | Contexte métier injecté ; pointer vers un volume pour le modifier sans redéployer |

> `GROK_FAST_MODEL` / `GROK_SMART_MODEL` ne sont plus lus (ils figeaient le bridge sur grok-3). Toutes les requêtes Grok passent par la Responses API (`POST /v1/responses`).

Tests : `pip install -r requirements-dev.txt && python -m pytest tests`

---

## Déploiement Railway

1. Push sur GitHub → connecter dans Railway
2. Configurer `XAI_API_KEY` dans le dashboard
3. Railway lit le `Procfile` : `web: python main.py`
4. URL MCP à enregistrer dans Claude : `https://<projet>.up.railway.app/mcp`

> Pour forcer un rebuild : modifier `CACHE_BUST=1` dans les variables Railway.
