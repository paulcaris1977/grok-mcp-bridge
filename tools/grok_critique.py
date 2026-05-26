"""
tools/grok_critique.py
Analyse critique sans filtre : code, stratégie, risques business.
"""

import logging
from typing import Optional
from fastmcp import FastMCP

from grok_client import call_grok, get_model_for_task
from context import build_system_prompt

logger = logging.getLogger("grok-mcp-bridge.critique")

_CRITIQUE_PROMPT_TEMPLATE = """
Tu es un critique technique et business très direct, sans filtre et orienté résultats.
Analyse de façon critique et honnête le contenu suivant :

SUJET / CONTENU À ANALYSER :
{content}

{focus_instruction}

**RÉPONDS EXCLUSIVEMENT avec cette structure :**

## 🔍 Synthèse
(Résumé court de ce qui est analysé)

## ⚠️ Points Critiques
- 🔴 **Critique** (bloquant / risque majeur)
- 🟠 **Majeur** (à corriger rapidement)
- 🟡 **Mineur** (amélioration recommandée)

## ✅ Points Positifs
(Ce qui est bien fait)

## 🎯 Recommandations Actionnables
1. Action prioritaire...
2. ...
3. ...

## 📊 Score Global : X/10
(Justification en 2-3 lignes maximum)

**Style** : Direct, cash, professionnel. N'hésite pas à être sévère si nécessaire. Priorise l'impact business pour Taranis.
""".strip()


def register_critique(mcp: FastMCP) -> None:
    """Enregistre le tool grok_critique."""

    @mcp.tool(
        name="grok_critique",
        description="Analyse critique sans filtre (code, stratégie, risques business). Très puissant pour revue de code ou plans stratégiques."
    )
    async def grok_critique(
        content: str,
        focus: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        Analyse critique approfondie.

        Args:
            content: Code, document, stratégie ou idée à critiquer
            focus: Angle spécifique (sécurité, performance, risque commercial, etc.)
            session_id: Pour analyses itératives
        """
        return await _run_critique(content, focus=focus, session_id=session_id)


async def _run_critique(
    content: str,
    focus: Optional[str] = None,
    session_id: Optional[str] = None,
    temperature: float = 0.35,
) -> str:
    """Implémentation interne."""

    focus_instruction = f"\n**ANGLE D'ANALYSE DEMANDÉ :** {focus}" if focus else ""

    system_prompt = build_system_prompt(
        task_type="critique",
        extra_instructions=focus_instruction
    )

    prompt = _CRITIQUE_PROMPT_TEMPLATE.format(
        content=content.strip(),
        focus_instruction=focus_instruction
    )

    model = get_model_for_task("critique")

    logger.info(
        f"grok_critique → model={model} | focus={focus or 'general'} | "
        f"content_length={len(content)} | session={session_id or 'none'}"
    )

    try:
        return await call_grok(
            prompt=prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=3500,
            session_id=session_id,
            use_history=bool(session_id),
        )
    except Exception as e:
        logger.error(f"Error in grok_critique: {e}", exc_info=True)
        return f"""❌ Erreur lors de l'analyse critique :
{str(e)}
**Conseil :** Réessayez avec un contenu plus court ou un focus plus précis."""
