"""
router/router.py — Grok-Claude Bridge
Plus de routage par mots-clés : l'appelant (Claude ou Grok) choisit le mode
de grok_dispatch. Ce module ne fait que valider le mode et traduire les
anciennes valeurs de `task` pour ne pas casser les appelants existants.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class Mode(str, Enum):
    GENERAL  = "general"
    CRITIQUE = "critique"
    CODE     = "code"
    RESEARCH = "research"


# Anciennes valeurs de `task` (v2) → mode
_ALIASES = {
    "dispatch":  Mode.GENERAL,
    "review":    Mode.CRITIQUE,
    "code_test": Mode.CODE,
    "test":      Mode.CODE,
    "debug":     Mode.CODE,
    "search":    Mode.RESEARCH,
    "market":    Mode.RESEARCH,
}

MODE_HELP = (
    "general = question ouverte, réponse directe ; "
    "critique = revue sans filtre d'un plan, d'une stratégie ou d'un texte ; "
    "code = debug / correction de code (coller le code dans prompt) ; "
    "research = recherche web et X en direct avec sources citées"
)


def resolve_mode(mode: Optional[str] = None, task: Optional[str] = None) -> Mode:
    """mode prime sur task ; ni l'un ni l'autre → general. Valeur inconnue → ValueError."""
    raw = (mode or task or Mode.GENERAL.value).strip().lower()
    try:
        return Mode(raw)
    except ValueError:
        if raw in _ALIASES:
            return _ALIASES[raw]
    raise ValueError(f"mode inconnu '{raw}' — valeurs : {', '.join(m.value for m in Mode)}")
