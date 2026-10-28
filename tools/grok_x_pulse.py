"""
tools/grok_x_pulse.py
Ce qui se dit sur X à propos d'une marque, d'une distillerie ou d'un sujet
(outil serveur x_search de xAI, filtré par période et comptes).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from fastmcp import FastMCP

from grok_client import call_grok
from context import build_system_prompt

logger = logging.getLogger("grok-mcp-bridge.x_pulse")

_MAX_HANDLES = 20   # limite xAI pour allowed_x_handles

_PULSE_PROMPT = """
Ce qui se dit sur X à propos de : {subject}
Période : depuis le {from_date}.{handles_line}

Structure :
## Volume et tonalité
(estimation honnête : peu / moyen / beaucoup de posts ; positif / négatif / mixte)
## Thèmes principaux
## Posts marquants
(pour chacun : auteur, date, une ligne, lien)
## Signaux pour Taranis
(demande en fûts, lancements, maturations, recrutements, tensions d'approvisionnement)

Si tu trouves très peu de posts, dis-le au lieu de remplir les rubriques.
""".strip()


def x_search_tool(days: int, handles: Optional[list[str]] = None, today: Optional[date] = None) -> dict:
    days = max(1, min(int(days), 90))
    tool: dict = {"type": "x_search",
                  "from_date": ((today or date.today()) - timedelta(days=days)).isoformat()}
    clean = [h.strip().lstrip("@") for h in (handles or []) if h and h.strip()]
    if clean:
        tool["allowed_x_handles"] = clean[:_MAX_HANDLES]
    return tool


def register_x_pulse(mcp: FastMCP) -> None:

    @mcp.tool(
        name="grok_x_pulse",
        description=(
            "Ce qui se dit sur X (Twitter) d'une marque, d'une distillerie, d'un concurrent ou d'un sujet : "
            "volume, tonalité, thèmes, posts marquants avec liens, signaux pour Taranis. "
            "days = période en jours (1-90, défaut 7) ; handles = comptes X à cibler (sans @, 20 max) ; "
            "effort = low | medium | high | max."
        ),
    )
    async def grok_x_pulse(
        subject: str,
        days: int = 7,
        handles: Optional[list[str]] = None,
        effort: str = "medium",
    ) -> str:
        tool = x_search_tool(days, handles)
        handles_line = f"\nComptes ciblés : {', '.join(tool['allowed_x_handles'])}." if "allowed_x_handles" in tool else ""
        logger.info("grok_x_pulse | subject_len=%d | from=%s | handles=%s | effort=%s",
                    len(subject), tool["from_date"], tool.get("allowed_x_handles"), effort)
        try:
            return await call_grok(
                prompt=_PULSE_PROMPT.format(subject=subject, from_date=tool["from_date"], handles_line=handles_line),
                system_prompt=build_system_prompt(task_type="research"),
                effort=effort,
                tools=[tool],
            )
        except Exception as exc:
            logger.error("grok_x_pulse: %s", exc, exc_info=True)
            return f"❌ Erreur grok_x_pulse ({type(exc).__name__}) : {exc}"
