"""
config.py — Grok-Claude Bridge
Centralise toutes les variables d'environnement Railway.
Pattern cohérent avec GROK_SMART_MODEL / GROK_FAST_MODEL existants.
"""

import os

# ── Grok (xAI) ────────────────────────────────────────────────────────────────
XAI_API_KEY      = os.environ.get("XAI_API_KEY", "")
GROK_BASE_URL    = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")
GROK_FAST_MODEL  = os.environ.get("GROK_FAST_MODEL", "grok-3-mini")
GROK_SMART_MODEL = os.environ.get("GROK_SMART_MODEL", "grok-3")

# ── Claude (Anthropic) — NOUVEAU pour le mode debate ─────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_BASE_URL   = os.environ.get("CLAUDE_BASE_URL", "https://api.anthropic.com/v1")
CLAUDE_MODEL      = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")

# ── Debate ────────────────────────────────────────────────────────────────────
DEBATE_MAX_TURNS      = int(os.environ.get("DEBATE_MAX_TURNS", "2"))       # réduit à 2 (Railway timeout)
DEBATE_MAX_TOKENS     = int(os.environ.get("DEBATE_MAX_TOKENS", "1024"))    # tokens/réponse par tour
DEBATE_HISTORY_KEEP   = int(os.environ.get("DEBATE_HISTORY_KEEP", "4"))     # nb messages récents à garder
DEBATE_TIMEOUT_S      = float(os.environ.get("DEBATE_TIMEOUT_S", "90.0"))   # timeout global debate
DEBATE_MAX_TOTAL_TOKENS = int(os.environ.get("DEBATE_MAX_TOTAL_TOKENS", "8000"))  # plafond tokens cumulés/session

# ── HTTP ──────────────────────────────────────────────────────────────────────
HTTP_TIMEOUT      = float(os.environ.get("HTTP_TIMEOUT", "30.0"))   # 30s × 2 tentatives × 2 LLMs × 2 tours ≤ 240s worst case, wait_for(90s) coupe proprement
HTTP_MAX_RETRIES  = int(os.environ.get("HTTP_MAX_RETRIES", "1"))     # 1 retry = 2 tentatives max


def validate_api_keys() -> None:
    """
    Appelée au démarrage dans main.py.
    Lève ValueError immédiatement si une clé critique est absente — fail fast.
    """
    missing = [k for k in ("XAI_API_KEY", "ANTHROPIC_API_KEY")
               if not os.environ.get(k)]
    if missing:
        raise ValueError(
            f"❌ Variables Railway manquantes : {', '.join(missing)}. "
            "Le bridge ne peut pas démarrer sans ces clés."
        )
