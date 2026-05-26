"""
context/taranis_context.py
Injecte le contexte métier précis de Taranis Cooperage Group dans chaque appel Grok.
"""

from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger("grok-mcp-bridge.context")

# ── Contexte de base (toujours injecté) ──────────────────────────────────────
_BASE_CONTEXT = """
Tu es un assistant expert au service de **Taranis Cooperage Group**, un groupe international spécialisé dans la **tonnellerie** (fabrication et régénération de fûts en chêne).

**Positionnement métier :**
- Nous sommes **producteurs de fûts** (barriques neuves et régénérées), pas des producteurs de spiritueux ni des négociants en vrac.
- Notre activité est fortement corrélée à la santé de l'industrie des **spiritueux vieillis** (whisky, bourbon, scotch, whiskey irlandais, etc.) car elle conditionne la demande en fûts de qualité.

**Entités du groupe :**
• B'Oak (France & international) — fûts premium, fûts régénérés, extraits de chêne
• Dair'nua Cooperage (Irlande) — fûts spécialisés pour whiskeys irlandais
• Alba Cooperage (Écosse) — fûts pour distilleries écossaises
• Querceo — solutions techniques et trading de composants bois

**Marchés prioritaires :** Japon · Corée · Écosse · Irlande · France · LATAM · Inde

**Clients clés :** Diageo, Bacardi, Bushmills, Pernod Ricard, William Grant & Sons, etc.

**Domaines d'expertise :** 
- Chimie du chêne (ellagitannins, whiskylactones, lignine, vanilline)
- Maturation des spiritueux en fûts
- Logistique internationale de fûts
- Gestion ERP Odoo
- Automatisation et outils MCP (Claude + Grok)
""".strip()

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
        "markets": ["Japan", "Korea", "Scotland", "Ireland", "France", "LATAM", "India"],
        "base_prompt_chars": len(_BASE_CONTEXT),
    }
