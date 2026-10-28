"""
workflow.py — Grok-Claude Bridge
Chaîne générique d'étapes Grok / Claude, décrite en JSON.

steps = liste d'étapes ; un élément peut aussi être une liste d'étapes lancées en parallèle.
Étape : {"id": "marche", "agent": "grok" | "claude", "prompt": "... {{input}} ... {{autre_id}} ...",
         "effort": "medium", "sources": "web", "schema": {...}, "max_tokens": 2000}
{{input}} = l'entrée du workflow ; {{id}} = la sortie d'une étape d'un groupe précédent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Union

from context import build_system_prompt
from grok_client import grok_respond, resolve_effort, search_tools
from llm_clients import claude_chat

logger = logging.getLogger("grok-mcp-bridge.workflow")

MAX_STEPS = 8
MAX_PARALLEL = 4
CLAUDE_TIMEOUT_S = 120.0
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_REF_RE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")
_STEP_KEYS = {"id", "agent", "prompt", "effort", "sources", "schema", "max_tokens"}

Progress = Callable[[str], Any]


@dataclass
class Step:
    id: str
    prompt: str
    agent: str = "grok"
    effort: str = "medium"
    sources: Optional[str] = None
    schema: Optional[dict] = None
    max_tokens: Optional[int] = None


@dataclass
class StepOutput:
    id: str
    agent: str
    text: str
    model: str
    footer: str = ""
    cost_usd: Optional[float] = None


@dataclass
class WorkflowResult:
    outputs: list[StepOutput] = field(default_factory=list)
    error: str = ""

    @property
    def grok_cost(self) -> float:
        return sum(o.cost_usd or 0.0 for o in self.outputs)


def parse_steps(raw: Union[str, list]) -> list[list[Step]]:
    """Valide la description JSON → groupes d'étapes (chaque groupe tourne en parallèle)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"steps n'est pas du JSON valide : {exc}") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("steps doit être une liste non vide d'étapes")

    groups: list[list[Step]] = []
    known: set[str] = set()
    total = 0
    for n, item in enumerate(raw, 1):
        items = item if isinstance(item, list) else [item]
        if not items or len(items) > MAX_PARALLEL:
            raise ValueError(f"groupe {n} : 1 à {MAX_PARALLEL} étapes en parallèle")
        group: list[Step] = []
        for spec in items:
            if not isinstance(spec, dict):
                raise ValueError(f"groupe {n} : chaque étape est un objet JSON")
            unknown = set(spec) - _STEP_KEYS
            if unknown:
                raise ValueError(f"étape {spec.get('id', '?')} : champs inconnus {sorted(unknown)}")
            step = Step(**spec)
            if not _ID_RE.match(str(step.id)):
                raise ValueError(f"id d'étape invalide '{step.id}' (minuscules, chiffres, _)")
            if step.id in known or step.id == "input" or any(s.id == step.id for s in group):
                raise ValueError(f"id d'étape en double ou réservé : '{step.id}'")
            if step.agent not in ("grok", "claude"):
                raise ValueError(f"étape {step.id} : agent = grok | claude")
            if not str(step.prompt or "").strip():
                raise ValueError(f"étape {step.id} : prompt vide")
            for ref in _REF_RE.findall(step.prompt):
                if ref != "input" and ref not in known:
                    raise ValueError(f"étape {step.id} : {{{{{ref}}}}} ne désigne aucune étape "
                                     "d'un groupe précédent")
            if step.agent == "grok":
                step.effort = resolve_effort(step.effort)
                if step.sources:
                    search_tools(step.sources)
            elif step.sources or step.schema:
                raise ValueError(f"étape {step.id} : sources et schema sont réservés à Grok")
            group.append(step)
        known |= {s.id for s in group}
        total += len(group)
        groups.append(group)
    if total > MAX_STEPS:
        raise ValueError(f"{total} étapes : maximum {MAX_STEPS}")
    return groups


def _fill(prompt: str, values: dict[str, str]) -> str:
    return _REF_RE.sub(lambda m: values.get(m.group(1), m.group(0)), prompt)


async def _run_step(step: Step, values: dict[str, str]) -> StepOutput:
    from tools.grok_structured import schema_format

    prompt = _fill(step.prompt, values)
    messages = [{"role": "system", "content": build_system_prompt(task_type="dispatch")},
                {"role": "user", "content": prompt}]
    if step.agent == "claude":
        text, model = await claude_chat(messages, max_tokens=step.max_tokens or 2500,
                                        temperature=0.3, timeout=CLAUDE_TIMEOUT_S)
        return StepOutput(step.id, "claude", text, model)
    result = await grok_respond(
        messages, effort=step.effort, max_output_tokens=step.max_tokens,
        tools=search_tools(step.sources) if step.sources else None,
        text_format=schema_format(step.schema, step.id) if step.schema else None)
    text = result.text if step.schema else result.render(footer=False)
    return StepOutput(step.id, "grok", text, result.model, result.footer(), result.cost_usd)


async def run_workflow(
    steps: Union[str, list],
    input: str = "",
    progress: Optional[Progress] = None,
) -> WorkflowResult:
    groups = parse_steps(steps)
    values: dict[str, str] = {"input": input}
    out = WorkflowResult()
    total = sum(len(g) for g in groups)
    done = 0

    for n, group in enumerate(groups, 1):
        names = ", ".join(s.id for s in group)
        if progress:
            progress(f"groupe {n}/{len(groups)} ({names}) — {done}/{total} étapes faites")
        logger.info("workflow groupe %d/%d : %s", n, len(groups), names)
        results = await asyncio.gather(*(_run_step(s, values) for s in group), return_exceptions=True)
        for step, res in zip(group, results):
            if isinstance(res, Exception):
                out.error = f"étape {step.id} ({step.agent}) : {type(res).__name__} : {res}"
                logger.error("workflow: %s", out.error)
                return out
            out.outputs.append(res)
            values[step.id] = res.text
            done += 1
    if progress:
        progress(f"terminé — {done}/{total} étapes")
    return out


def format_workflow(result: WorkflowResult) -> str:
    lines = ["# 🔗 Workflow Grok × Claude"]
    if result.error:
        lines.append(f"\n⚠️ **Arrêt :** {result.error}")
    if result.outputs:
        last = result.outputs[-1]
        lines.append(f"\n## Résultat ({last.id}, {last.agent})\n\n{last.text}")
        lines.append("\n---\n\n## Étapes")
        for o in result.outputs:
            meta = o.footer or f"`{o.model}` (coût Claude non compté)"
            lines.append(f"\n<details><summary>{o.id} — {o.agent}</summary>\n\n{o.text}\n\n{meta}\n\n</details>")
    lines.append(f"\n---\nCoût Grok estimé ≈ {result.grok_cost:.3f} $ (Claude non compté)")
    return "\n".join(lines)
