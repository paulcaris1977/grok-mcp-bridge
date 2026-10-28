"""
tools/grok_structured.py
Sortie JSON garantie par schéma (structured outputs xAI, Responses API text.format).
Pour enchaîner Grok avec d'autres outils (Odoo, Foudre, tableurs) sans parsing fragile.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional, Union

from fastmcp import FastMCP

from grok_client import grok_respond, search_tools
from context import build_system_prompt

logger = logging.getLogger("grok-mcp-bridge.structured")


def schema_format(schema: Union[dict, str], name: str = "result") -> dict:
    """Valide le schéma et construit text.format pour la Responses API."""
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except json.JSONDecodeError as exc:
            raise ValueError(f"schema n'est pas du JSON valide : {exc}") from exc
    if not isinstance(schema, dict) or "type" not in schema:
        raise ValueError("schema doit être un objet JSON Schema avec un champ 'type'")
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", name or "result")[:64] or "result"
    return {"type": "json_schema", "name": safe_name, "schema": schema, "strict": True}


def register_structured(mcp: FastMCP) -> None:

    @mcp.tool(
        name="grok_structured",
        description=(
            "Demande à Grok une réponse JSON conforme à un JSON Schema fourni (sortie garantie par xAI). "
            "Pour extraire ou produire des données exploitables par d'autres outils. "
            "schema = objet JSON Schema (ou sa chaîne JSON) ; sources = web | x | web+x pour chercher ; "
            "renvoie {data, meta} avec modèle, coût estimé et sources."
        ),
    )
    async def grok_structured(
        prompt: str,
        schema: Union[dict, str],
        name: str = "result",
        effort: str = "medium",
        sources: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        text_format = schema_format(schema, name)
        result = await grok_respond(
            [{"role": "system", "content": build_system_prompt(task_type="dispatch")},
             {"role": "user", "content": prompt}],
            effort=effort, model=model,
            tools=search_tools(sources) if sources else None,
            text_format=text_format,
        )
        try:
            data = json.loads(result.text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Grok n'a pas renvoyé de JSON valide ({exc}) : {result.text[:300]}") from exc
        return {
            "data": data,
            "meta": {
                "model": result.model,
                "effort": result.effort,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "tool_calls": result.tool_calls,
                "cost_usd_estimate": round(result.cost_usd, 4) if result.cost_usd is not None else None,
                "citations": result.citations,
            },
        }
