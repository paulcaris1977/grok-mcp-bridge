"""
context/taranis_context.py
Injecte le contexte métier précis de Taranis Cooperage Group dans chaque appel Grok.
"""

from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("grok-mcp-bridge.context")

# ── Contexte de base (toujours injecté) ──────────────────────────────────────
# Chargé depuis un fichier Markdown pour être corrigé sans toucher au code.
# TARANIS_CONTEXT_PATH permet de pointer vers une copie sur volume Railway.
_DEFAULT_CONTEXT_PATH = Path(__file__).with_name("taranis_context.md")


def _load_base_context() -> str:
    override = os.environ.get("TARANIS_CONTEXT_PATH", "").strip()
    if override:
        try:
            return Path(override).read_text(encoding="utf-8").strip()
        except OSError as exc:
            logger.warning("TARANIS_CONTEXT_PATH illisible (%s), contexte du repo utilisé", exc)
    return _DEFAULT_CONTEXT_PATH.read_text(encoding="utf-8").strip()


_BASE_CONTEXT = _load_base_context()

# ── Contextes additionnels par type de tâche ─────────────────────────────────
_CRITIQUE_EXTRA = """
Pour les analyses critiques, sois particulièrement vigilant sur :
- Les risques commerciaux et financiers liés au marché des spiritueux vieillis
- L'impact sur la demande en fûts (notre cœur de métier)
- Les opportunités ou menaces pour nos capacités de production et nos clients distillateurs.
"""

_RESEARCH_EXTRA = """
Pour les recherches de marché :
- Concentre-toi sur l'industrie des spiritueux **vieillis** (bourbon, scotch, whisky, etc.)
- Analyse toujours l'impact sur la **demande en fûts et barriques**
- Identifie les opportunités pour un tonnelier comme Taranis (nouveaux marchés, tendances maturation, etc.)
"""

_CODE_EXTRA = """
Pour les tâches de code :
- Priorise la compatibilité Python 3.11+, FastMCP, Railway, Odoo Online
- Respecte l'architecture modulaire du Grok MCP Bridge
- Sois attentif à la robustesse et à la gestion des erreurs
"""

_DISPATCH_EXTRA = """
Tu travailles pour Taranis Cooperage Group, tonnelier international.
Adapte tes réponses au contexte d'un fabricant de fûts pour spiritueux premium.
Sois concret, orienté business et actionnable.
"""


def build_system_prompt(
    task_type: str = "dispatch",
    extra_instructions: Optional[str] = None,
    include_base: bool = True,
) -> str:
    """
    Construit le system prompt complet avec le contexte Taranis.
    """
    parts: list[str] = []

    if include_base:
        parts.append(_BASE_CONTEXT)

    extras = {
        "critique":  _CRITIQUE_EXTRA,
        "review":    _CRITIQUE_EXTRA,
        "code_test": _CODE_EXTRA,
        "code":      _CODE_EXTRA,
        "research":  _RESEARCH_EXTRA,
        "dispatch":  _DISPATCH_EXTRA,
    }

    if task_type in extras:
        parts.append(extras[task_type].strip())

    if extra_instructions:
        parts.append(extra_instructions.strip())

    system_prompt = "\n\n".join(parts)

    logger.debug(f"System prompt built for task_type='{task_type}' — {len(system_prompt)} chars")
    return system_prompt


def get_context_summary() -> dict:
    """Résumé pour diagnostic."""
    return {
        "group": "Taranis Cooperage Group",
        "activity": "Tonnellerie (fabrication de fûts)",
        "markets": ["Japan", "Korea", "Scotland", "Ireland", "France", "LATAM", "India", "Georgia", "China"],
        "base_prompt_chars": len(_BASE_CONTEXT),
    }
