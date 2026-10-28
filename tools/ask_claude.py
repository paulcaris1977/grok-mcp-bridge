"""
tools/ask_claude.py
Interroger Claude depuis Grok (ou tout client MCP), au même niveau que les outils Grok :
contexte Taranis, notes de projet, vraie session, effort, sortie JSON, coût estimé.
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Union

from fastmcp import FastMCP

import store
from context import build_system_prompt
from llm_clients import claude_respond
from tools.project_memory import format_notes

logger = logging.getLogger("grok-mcp-bridge.ask_claude")

_RULES = (
    "Tu réponds à un autre agent (souvent Grok) via le bridge. "
    "N'invente aucun chiffre. Si une note de projet contredit une source publique, signale l'écart. "
    "Distingue fait sourcé, hypothèse interne et donnée absente."
)


def history_key(session_id: str) -> str:
    """Sessions Claude séparées des sessions Grok dans la même table."""
    return f"claude:{session_id}"


def register_ask_claude(mcp: FastMCP) -> None:
    @mcp.tool(
        name="ask_claude",
        description=(
            "Interroge Claude (Anthropic) avec le contexte Taranis. "
            "project = notes de projet partagées à injecter (save_project_note) ; "
            "session_id = conversation suivie (Claude voit les échanges précédents de cette session) ; "
            "effort = low | medium | high | xhigh | max ; "
            "schema = JSON Schema → renvoie {data, meta} avec un JSON garanti. "
            "Claude n'a pas d'accès web ici : pour des faits récents, passer par grok_research."
        ),
    )
    async def ask_claude(
        prompt: str,
        project: str = "",
        session_id: Optional[str] = None,
        effort: str = "medium",
        schema: Union[dict, str, None] = None,
        max_tokens: Optional[int] = None,
    ):  # texte, ou {data, meta} avec schema ; sans annotation, FastMCP n'enveloppe pas le dict
        project = project.strip()
        question = prompt.strip()
        user = question
        if project:
            notes = format_notes(project)
            user = (notes + "\n\nQuestion:\n" + question) if notes else (
                f"Aucune note enregistrée pour le projet '{project}'. "
                "Réponds seulement à la question, et dis que le contexte projet est absent.\n\n" + question)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": build_system_prompt(task_type="dispatch", extra_instructions=_RULES)}]
        if session_id:
            messages.extend(store.get_history(history_key(session_id)))
        messages.append({"role": "user", "content": user})

        try:
            result = await claude_respond(messages, effort=effort, schema=schema,
                                          max_tokens=max_tokens or (8000 if schema is not None else 6000),
                                          timeout=180.0)
        except ValueError as exc:
            return f"Erreur: {exc}"
        except Exception as exc:
            logger.error("ask_claude failed: %s", exc, exc_info=True)
            return f"Erreur appel Claude: {exc}"

        if session_id:
            store.append_history(history_key(session_id), [{"role": "user", "content": question},
                                                           {"role": "assistant", "content": result.text}])

        if schema is None:
            return f"{result.text}\n\n---\n{result.footer()}"
        try:
            data = json.loads(result.text)
        except json.JSONDecodeError as exc:
            return f"Erreur: Claude n'a pas renvoyé de JSON valide ({exc}) : {result.text[:300]}"
        return {
            "data": data,
            "meta": {
                "model": result.model,
                "effort": result.effort,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cost_usd_estimate": round(result.cost_usd, 4) if result.cost_usd is not None else None,
            },
        }
