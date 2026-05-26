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
| `grok_research` | Recherche avec `market=` et `depth="deep"` explicites |

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
| `GROK_SMART_MODEL` | `grok-3` | Critique, research, code |
| `GROK_FAST_MODEL` | `grok-3-mini` | Dispatch générique |
| `PORT` | `8000` | Fixé automatiquement par Railway |

---

## Déploiement Railway

1. Push sur GitHub → connecter dans Railway
2. Configurer `XAI_API_KEY` dans le dashboard
3. Railway lit le `Procfile` : `web: python main.py`
4. URL MCP à enregistrer dans Claude : `https://<projet>.up.railway.app/mcp`

> Pour forcer un rebuild : modifier `CACHE_BUST=1` dans les variables Railway.
