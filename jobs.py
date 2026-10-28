"""
jobs.py — Grok-Claude Bridge
Tâches de fond : un appel long (recherche max, débat 4 tours, workflow) est lancé
dans le process et suivi par identifiant, au lieu de bloquer l'appel MCP.

État dans SQLite (store.py). Un redémarrage du serveur interrompt les tâches en cours :
elles passent en statut « interrupted » au démarrage suivant.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import uuid
from typing import Any, Awaitable, Callable

import store

logger = logging.getLogger("grok-mcp-bridge.jobs")

JOB_TIMEOUT_S = float(os.environ.get("JOB_TIMEOUT_S", "900"))
JOB_CONCURRENCY = int(os.environ.get("JOB_CONCURRENCY", "3"))

Runner = Callable[..., Awaitable[str]]

_semaphore: asyncio.Semaphore | None = None
_tasks: set[asyncio.Task] = set()   # références fortes : sinon le GC peut annuler une tâche


async def _research(query: str, market: str | None = None, effort: str = "high",
                    sources: str = "web+x", model: str | None = None) -> str:
    from tools.grok_research import _run_research
    return await _run_research(query, market=market, effort=effort, sources=sources, model=model)


async def _verify(query: str, market: str | None = None, effort: str = "high",
                  sources: str = "web+x") -> str:
    from orchestration import run_verify
    return await run_verify(query, market=market, effort=effort, sources=sources)


async def _cross_check(question: str, effort: str = "high", sources: str | None = None,
                       judge: str = "claude") -> str:
    from orchestration import run_cross_check
    return await run_cross_check(question, effort=effort, sources=sources, judge=judge)


async def _debate(prompt: str, turns: int | None = 4, topic_context: str | None = None,
                  temperature: float = 0.7, judge: str = "claude") -> str:
    from tools.grok_debate import debate_report
    return await debate_report(prompt, turns, topic_context, temperature, judge)


async def _workflow(steps: Any, input: str = "", *, progress: Callable[[str], Any]) -> str:
    from workflow import format_workflow, run_workflow
    return format_workflow(await run_workflow(steps, input, progress=progress))


RUNNERS: dict[str, Runner] = {
    "research": _research,
    "verify": _verify,
    "cross_check": _cross_check,
    "debate": _debate,
    "workflow": _workflow,
}


def _check(kind: str, params: dict[str, Any]) -> Runner:
    runner = RUNNERS.get(kind)
    if runner is None:
        raise ValueError(f"kind inconnu '{kind}' (valeurs : {', '.join(RUNNERS)})")
    try:
        inspect.signature(runner).bind(**params, **({"progress": None} if kind == "workflow" else {}))
    except TypeError as exc:
        raise ValueError(f"params invalides pour {kind} : {exc}") from exc
    if kind == "workflow":
        from workflow import parse_steps
        parse_steps(params["steps"])
    return runner


async def start(kind: str, params: dict[str, Any]) -> str:
    """Valide, enregistre et lance la tâche. Renvoie son identifiant."""
    global _semaphore
    kind = (kind or "").strip().lower()
    params = params or {}
    runner = _check(kind, params)
    job_id = uuid.uuid4().hex[:12]
    store.create_job(job_id, kind, params)
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(JOB_CONCURRENCY)

    def progress(text: str) -> None:
        store.update_job(job_id, progress=text)

    async def _run() -> None:
        async with _semaphore:
            store.update_job(job_id, status="running", progress="démarrée")
            logger.info("job %s (%s) démarré", job_id, kind)
            kwargs = {"progress": progress} if kind == "workflow" else {}
            try:
                result = await asyncio.wait_for(runner(**params, **kwargs), timeout=JOB_TIMEOUT_S)
            except asyncio.TimeoutError:
                store.update_job(job_id, status="failed", error=f"Timeout {JOB_TIMEOUT_S:.0f}s")
            except asyncio.CancelledError:
                store.update_job(job_id, status="interrupted", error="Tâche annulée")
                raise
            except Exception as exc:
                logger.error("job %s: %s", job_id, exc, exc_info=True)
                store.update_job(job_id, status="failed", error=f"{type(exc).__name__} : {exc}")
            else:
                store.update_job(job_id, status="done", progress="terminée", result=result)
            logger.info("job %s (%s) fini", job_id, kind)

    task = asyncio.create_task(_run(), name=f"job-{job_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return job_id


async def wait(job_id: str, wait_s: float) -> dict[str, Any] | None:
    """Relit la tâche, en attendant jusqu'à wait_s secondes qu'elle se termine."""
    deadline = asyncio.get_running_loop().time() + max(0.0, wait_s)
    while True:
        job = store.get_job(job_id)
        if job is None or job["status"] not in ("queued", "running"):
            return job
        if asyncio.get_running_loop().time() >= deadline:
            return job
        await asyncio.sleep(2)
