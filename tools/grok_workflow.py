"""
tools/grok_workflow.py
Workflow générique Grok × Claude décrit en JSON (voir workflow.py).
"""

from __future__ import annotations

import json
import logging
from typing import Union

from fastmcp import FastMCP

import jobs
from workflow import MAX_PARALLEL, MAX_STEPS, format_workflow, run_workflow

logger = logging.getLogger("grok-mcp-bridge.workflow_tool")


def register_workflow(mcp: FastMCP) -> None:

    @mcp.tool(
        name="grok_workflow",
        description=(
            "Enchaîne des étapes Grok et Claude décrites en JSON. steps = liste ; un élément peut être "
            "une liste d'étapes lancées en parallèle. Étape : {\"id\": \"marche\", \"agent\": \"grok\"|\"claude\", "
            "\"prompt\": \"... {{input}} ... {{autre_id}} ...\", \"effort\": \"medium\", \"sources\": \"web\", "
            "\"schema\": {...}, \"max_tokens\": 2000}. {{input}} = input ; {{id}} = sortie d'une étape précédente. "
            f"Max {MAX_STEPS} étapes, {MAX_PARALLEL} en parallèle. sources et schema : Grok seulement. "
            "background = true (défaut) : renvoie un job_id à suivre avec grok_get_job ; false : attend le résultat. "
            "Exemple : [{\"id\":\"faits\",\"agent\":\"grok\",\"prompt\":\"Chiffres clés : {{input}}\",\"sources\":\"web\"},"
            "{\"id\":\"avis\",\"agent\":\"claude\",\"prompt\":\"Critique ces chiffres : {{faits}}\"}]"
        ),
    )
    async def grok_workflow(steps: Union[list, str], input: str = "", background: bool = True) -> str:
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except json.JSONDecodeError as exc:
                return f"❌ steps n'est pas du JSON valide : {exc}"
        if background:
            try:
                job_id = await jobs.start("workflow", {"steps": steps, "input": input})
            except ValueError as exc:
                return f"❌ Workflow refusé : {exc}"
            return (f"🚀 Workflow lancé : job_id = `{job_id}`.\n"
                    f"Suivre avec grok_get_job(job_id=\"{job_id}\", wait_s=50).")
        try:
            return format_workflow(await run_workflow(steps, input))
        except ValueError as exc:
            return f"❌ Workflow refusé : {exc}"
        except Exception as exc:
            logger.error("grok_workflow: %s", exc, exc_info=True)
            return f"❌ Erreur grok_workflow ({type(exc).__name__}) : {exc}"
