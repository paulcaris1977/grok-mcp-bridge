"""
tools/grok_orchestration.py
Schémas nommés Grok × Claude : grok_verify et grok_cross_check.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastmcp import FastMCP

from orchestration import run_cross_check, run_verify

logger = logging.getLogger("grok-mcp-bridge.orchestration_tools")


def register_orchestration(mcp: FastMCP) -> None:

    @mcp.tool(
        name="grok_verify",
        description=(
            "Recherche puis contrôle : Grok cherche sur le web/X avec sources citées, puis Claude "
            "contrôle chaque chiffre et fait (✅ sourcé, ⚠️ non sourcé, ❌ douteux) et note la fiabilité. "
            "À préférer à grok_research quand les chiffres vont servir (prix, volumes, parts de marché). "
            "effort = low | medium | high | max ; sources = web | x | web+x."
        ),
    )
    async def grok_verify(
        query: str,
        market: Optional[str] = None,
        effort: str = "medium",
        sources: str = "web+x",
    ) -> str:
        logger.info("grok_verify | effort=%s | sources=%s | market=%s", effort, sources, market)
        try:
            return await run_verify(query, market=market, effort=effort, sources=sources)
        except Exception as exc:
            logger.error("grok_verify: %s", exc, exc_info=True)
            return f"❌ Erreur grok_verify ({type(exc).__name__}) : {exc}"

    @mcp.tool(
        name="grok_cross_check",
        description=(
            "Contre-expertise : la même question est posée à Grok et à Claude en parallèle, "
            "sans qu'ils voient la réponse de l'autre, puis un arbitre compare (accords, désaccords, "
            "ce qu'un seul mentionne, à vérifier, réponse consolidée). "
            "sources = web | x | web+x pour laisser Grok chercher (Claude n'a pas le web). "
            "judge = claude | grok."
        ),
    )
    async def grok_cross_check(
        question: str,
        effort: str = "medium",
        sources: Optional[str] = None,
        judge: str = "claude",
    ) -> str:
        logger.info("grok_cross_check | effort=%s | sources=%s | judge=%s", effort, sources, judge)
        try:
            return await run_cross_check(question, effort=effort, sources=sources, judge=judge)
        except Exception as exc:
            logger.error("grok_cross_check: %s", exc, exc_info=True)
            return f"❌ Erreur grok_cross_check ({type(exc).__name__}) : {exc}"
