"""
tools/ask_claude.py
Outil MCP manquant : interroger Claude depuis Grok, avec les notes de projet.
Réutilise llm_clients.claude_chat. Ne remplace pas grok_dispatch.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastmcp import FastMCP

from llm_clients import claude_chat
from tools.project_memory import format_notes

logger = logging.getLogger("grok-mcp-bridge.ask_claude")

_SYSTEM = (
    "Tu réponds à Grok, qui prépare un dossier marché. "
    "Ne invente aucun chiffre. Si une note de projet contredit une source publique, signale l'écart. "
    "Distingue fait sourcé, hypothèse interne et donnée absente. Réponds en français."
)


def register_ask_claude(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ask_claude",
        description=(
            "Interroge Claude (Anthropic) avec le contexte d'un projet partagé. "
            "À utiliser pour récupérer les notes Nalmaia ou faire relire un chiffre par Claude. "
            "Ne lit pas les conversations Claude hors de ce bridge : seulement l'API et les notes save_project_note."
        ),
    )
    async def ask_claude(
        prompt: str,
        project: str = "nalmaia",
        session_id: Optional[str] = None,
        temperature: float = 0.2,
    ) -> str:
        notes = format_notes(project.strip() or "nalmaia")
        user = prompt.strip()
        if notes:
            user = notes + "\n\nQuestion:\n" + user
        else:
            user = (
                f"Aucune note enregistrée pour le projet '{project}'. "
                "Réponds seulement à la question, et dis que le contexte projet est absent.\n\n"
                + user
            )
        if session_id:
            user = f"[session_id={session_id}]\n" + user
        try:
            content, model = await claude_chat(
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
        except Exception as exc:
            logger.error("ask_claude failed: %s", exc, exc_info=True)
            return f"Erreur appel Claude: {exc}"
        return f"[claude model={model} project={project}]\n{content}"
