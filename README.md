# Grok MCP Bridge v2.0

Bridge de production reliant **Claude ↔ Grok (xAI)**, déployé sur Railway.

## Pourquoi ce bridge ?

Claude est excellent pour raisonner et structurer. Grok apporte la **recherche web temps réel**, une **critique directe sans filtre**, et une forte capacité sur le code. Ce bridge donne accès aux deux depuis un seul point d'entrée MCP — avec le contexte métier Taranis Cooperage injecté automatiquement à chaque appel.

---

## Un seul tool à retenir : `grok_dispatch`

```
grok_dispatch(prompt="ta question ou instruction")
```

Le router analyse le prompt et choisit automatiquement le bon handler. Dans 80% des cas, c'est tout ce dont tu as besoin.

```
# Exemples — tout passe par grok_dispatch
grok_dispatch(prompt="Recherche les prix marché des fûts bourbon en Écosse 2026")
grok_dispatch(prompt="Critique ce plan commercial pour le marché japonais")
grok_dispatch(prompt="Corrige cette erreur Python Railway : TypeError...")
```

Override manuel si besoin : `grok_dispatch(prompt="...", task="critique")`

---

## Architecture

```
main.py                          ← Serveur FastMCP + enregistrement des tools
├── router/router.py             ← Cerveau : routing intelligent
├── tools/
│   ├── grok_dispatch.py         ← Point d'entrée unique recommandé
│   ├── grok_critique.py         ← Analyse critique sans filtre
│   ├── grok_code_test.py        ← Debug, correction et optimisation de code
│   └── grok_research.py         ← Recherche web + market intelligence
├── grok_client.py               ← Client Grok (retry, quota, historique)
├── utils/json_parser.py         ← Parsing JSON robuste
└── context/taranis_context.py   ← Contexte métier Taranis injecté automatiquement
```

---

## Tools disponibles

| Tool | Quand l'appeler directement |
|------|-----------------------------|
| `grok_dispatch` | **Toujours — point d'entrée principal** |
| `grok_critique` | Revue approfondie avec `focus=` précis (ex: "risque Corée") |
| `grok_code_test` | Debug itératif avec `session_id` + `error_message` |
| `grok_research` | Recherche web + X en direct (`sources="web" | "x" | "web+x"`), sources citées |

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
