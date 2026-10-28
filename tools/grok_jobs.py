"""
tools/grok_jobs.py
Tâches de fond : grok_start_job, grok_get_job, grok_list_jobs.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Union

from fastmcp import FastMCP

import jobs
import store

logger = logging.getLogger("grok-mcp-bridge.jobs_tools")

_STATUS_ICON = {"queued": "⏳", "running": "🔄", "done": "✅", "failed": "❌", "interrupted": "⚠️"}


def format_job(job: dict[str, Any]) -> str:
    icon = _STATUS_ICON.get(job["status"], "•")
    head = (f"{icon} Tâche `{job['id']}` ({job['kind']}) — **{job['status']}**"
            f"\nCréée {job['created_at']} · mise à jour {job['updated_at']}")
    if job.get("progress"):
        head += f"\nAvancement : {job['progress']}"
    if job["status"] == "done":
        return f"{head}\n\n---\n\n{job['result']}"
    if job.get("error"):
        return f"{head}\nErreur : {job['error']}"
    return head + "\n\nPas encore fini : rappeler grok_get_job (wait_s jusqu'à 50 pour attendre)."


def register_jobs(mcp: FastMCP) -> None:

    @mcp.tool(
        name="grok_start_job",
        description=(
            "Lance en arrière-plan un travail long et renvoie aussitôt un job_id à suivre avec grok_get_job. "
            "kind = research | verify | cross_check | debate | workflow ; params = les arguments de l'outil "
            "correspondant (research/verify : query, market, effort, sources ; cross_check : question, effort, "
            "sources, judge ; debate : prompt, turns, judge ; workflow : steps, input). "
            "Effort par défaut high (debate : 4 tours). Timeout 15 min."
        ),
    )
    async def grok_start_job(kind: str, params: Union[dict, str]) -> str:
        try:
            if isinstance(params, str):
                params = json.loads(params) if params.strip() else {}
            job_id = await jobs.start(kind, params)
        except (ValueError, json.JSONDecodeError) as exc:
            return f"❌ Tâche refusée : {exc}"
        warn = "" if store.is_persistent() else "\n⚠️ Pas de volume Railway : un redéploiement effacera le résultat."
        return (f"🚀 Tâche lancée : job_id = `{job_id}` ({kind}).\n"
                f"Suivre avec grok_get_job(job_id=\"{job_id}\", wait_s=50).{warn}")

    @mcp.tool(
        name="grok_get_job",
        description=(
            "État et résultat d'une tâche de fond. wait_s (0-50) : attendre jusqu'à ce délai "
            "que la tâche se termine avant de répondre, pour éviter de rappeler en boucle."
        ),
    )
    async def grok_get_job(job_id: str, wait_s: float = 0) -> str:
        job = await jobs.wait(job_id.strip(), min(max(wait_s, 0), 50))
        if job is None:
            return f"❌ Aucune tâche `{job_id}` (purgée après {store.JOB_RETENTION_DAYS} jours, ou perdue au redéploiement)."
        return format_job(job)

    @mcp.tool(
        name="grok_list_jobs",
        description="Liste les dernières tâches de fond (id, type, statut, avancement).",
    )
    async def grok_list_jobs(limit: int = 10) -> str:
        rows = store.list_jobs(max(1, min(limit, 50)))
        if not rows:
            return "Aucune tâche."
        return "\n".join(
            f"{_STATUS_ICON.get(r['status'], '•')} `{r['id']}` {r['kind']} — {r['status']}"
            f" · {r['created_at']}" + (f" · {r['progress']}" if r["progress"] else "")
            for r in rows)
