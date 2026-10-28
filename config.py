"""
config.py — Grok-Claude Bridge
Centralise toutes les variables d'environnement Railway.
Les profils d'effort Grok sont définis ici (EFFORT_PROFILES).
"""

import os

# ── Grok (xAI) ────────────────────────────────────────────────────────────────
XAI_API_KEY      = os.environ.get("XAI_API_KEY", "")
GROK_BASE_URL    = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")

# ── Profils d'effort (Responses API) ──────────────────────────────────────────
# Chaque niveau fixe : modèle, reasoning.effort, budget de sortie (raisonnement
# compris), nombre max de tours d'outils (recherches) et timeout de l'appel.
# Les anciennes variables GROK_FAST_MODEL / GROK_SMART_MODEL ne sont plus lues :
# elles valent grok-3 sur Railway et figeraient le bridge sur l'ancien modèle.
GROK_MODEL_LOW  = os.environ.get("GROK_MODEL_LOW", "grok-4.20-0309-non-reasoning")
GROK_MODEL_MAIN = os.environ.get("GROK_MODEL_MAIN", "grok-4.7")

EFFORT_PROFILES: dict[str, dict] = {
    "low":    {"model": GROK_MODEL_LOW,  "reasoning": None,     "max_output_tokens": 1500,  "max_turns": 2,  "timeout_s": 45.0},
    "medium": {"model": GROK_MODEL_MAIN, "reasoning": "low",    "max_output_tokens": 4000,  "max_turns": 3,  "timeout_s": 90.0},
    "high":   {"model": GROK_MODEL_MAIN, "reasoning": "high",   "max_output_tokens": 8000,  "max_turns": 6,  "timeout_s": 180.0},
    "max":    {"model": GROK_MODEL_MAIN, "reasoning": "xhigh",  "max_output_tokens": 16000, "max_turns": 10, "timeout_s": 300.0},
}
DEFAULT_EFFORT = os.environ.get("GROK_DEFAULT_EFFORT", "medium")
# grok_vision : modèle fixe quel que soit l'effort (la doc xAI ne garantit l'image que sur grok-4.7)
GROK_VISION_MODEL = os.environ.get("GROK_VISION_MODEL", GROK_MODEL_MAIN)

# Modèles qui acceptent reasoning.effort (doc xAI : 4.5 → low/medium/high, xhigh traité comme high)
EFFORT_CAPABLE_MODELS = {m.strip() for m in os.environ.get(
    "GROK_EFFORT_MODELS", "grok-4.7,grok-4.6,grok-4.5").split(",") if m.strip()}
# Modèles de raisonnement : on ne leur envoie pas de temperature
REASONING_MODELS = EFFORT_CAPABLE_MODELS | {"grok-4.3", "grok-4.20-0309-reasoning"}

# Prix en $ par million de tokens (entrée, sortie), < 200k tokens — docs.x.ai, oct. 2026.
# Sert à l'estimation affichée sous chaque réponse, pas à la facturation.
GROK_PRICES: dict[str, tuple[float, float]] = {
    "grok-4.7": (2.00, 6.00),
    "grok-4.6": (2.00, 6.00),
    "grok-4.5": (2.00, 6.00),
    "grok-4.3": (1.25, 2.50),
    "grok-4.20-0309-reasoning": (1.25, 2.50),
    "grok-4.20-0309-non-reasoning": (1.25, 2.50),
}
GROK_TOOL_CALL_PRICE = 0.005   # $5 / 1 000 appels web_search ; x_search est facturé par post, donc estimation basse

# ── Claude (Anthropic) — NOUVEAU pour le mode debate ─────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_BASE_URL   = os.environ.get("CLAUDE_BASE_URL", "https://api.anthropic.com/v1")
CLAUDE_MODEL      = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
# output_config.effort (thinking adaptatif) ; Sonnet 5.5 refuse temperature ≠ défaut, on ne l'envoie plus
CLAUDE_EFFORTS        = ("low", "medium", "high", "xhigh", "max")
CLAUDE_DEFAULT_EFFORT = os.environ.get("CLAUDE_DEFAULT_EFFORT", "medium")
# Repli serveur en cas de refus (fallbacks "default") — seulement sur les modèles qui l'acceptent
CLAUDE_FALLBACK_MODELS = {m.strip() for m in os.environ.get(
    "CLAUDE_FALLBACK_MODELS", "claude-sonnet-5-5,claude-opus-5-5,claude-opus-5,claude-fable-5-1").split(",") if m.strip()}
# Prix en $ par million de tokens (entrée, sortie) — docs Anthropic, oct. 2026. Estimation, pas facturation.
CLAUDE_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
}

# ── Debate ────────────────────────────────────────────────────────────────────
DEBATE_MAX_TURNS      = int(os.environ.get("DEBATE_MAX_TURNS", "2"))       # réduit à 2 (Railway timeout)
DEBATE_MAX_TOKENS     = int(os.environ.get("DEBATE_MAX_TOKENS", "1024"))    # tokens/réponse par tour
DEBATE_HISTORY_KEEP   = int(os.environ.get("DEBATE_HISTORY_KEEP", "4"))     # nb messages récents à garder
DEBATE_TIMEOUT_S      = float(os.environ.get("DEBATE_TIMEOUT_S", "150.0"))  # timeout global debate (tours en parallèle + synthèse)
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
