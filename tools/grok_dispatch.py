"""
tools/grok_dispatch.py
Tool principal et point d'entrée unique recommandé pour Claude.
Implémente le dispatching intelligent vers les handlers spécialisés.
"""

import logging
from typing import Optional
from fastmcp import FastMCP

from grok_client import call_grok, get_model_for_task
from router.router import route, TaskType          # Import explicite
from context import build_system_prompt

logger = logging.getLogger("grok-mcp-bridge.dispatch")


def register_dispatch(mcp: FastMCP) -> None:
    """Enregistre le tool principal de dispatch."""

    @mcp.tool(
        name="grok_dispatch",
        description="Point d'entrée unique vers Grok. Le bridge route automatiquement vers le meilleur handler (critique, code test, research, etc.). Recommandé."
    )
    async def grok_dispatch(
        prompt: str,
        task: Optional[str] = None,           # Override manuel : "critique", "code_test", "research", etc.
        session_id: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        """
        Point d'entrée principal pour Claude.
        Le router décide automatiquement du meilleur traitement.
        """
        try:
            # ── Décision de routing ─────────────────────────────────────
            decision = route(prompt, explicit_task=task)

            logger.info(
                f"grok_dispatch → routed to '{decision.task_type.value}' "
                f"(confidence={decision.confidence:.2f}, override={task is not None})"
            )

            # ── Délégation aux handlers spécialisés ─────────────────────
            if decision.task_type == TaskType.CRITIQUE:
                from tools.grok_critique import _run_critique
                return await _run_critique(
                    prompt=prompt,
                    session_id=session_id,
                    temperature=temperature
                )

            elif decision.task_type == TaskType.CODE_TEST:
                from tools.grok_code_test import _run_code_test
                # On essaie de détecter si le prompt contient du code
                return await _run_code_test(
                    code=prompt,                    # fallback simple
                    language="python",
                    context="Code envoyé via grok_dispatch",
                    session_id=session_id,
                    temperature=min(temperature, 0.3),   # plus basse pour du code
                )

            elif decision.task_type == TaskType.RESEARCH:
                from tools.grok_research import _run_research
                return await _run_research(
                    prompt=prompt,
                    session_id=session_id,
                    temperature=temperature
                )

            # ── Cas par défaut (question générale) ─────────────────────
            else:
                system_prompt = build_system_prompt(task_type="dispatch")
                model = get_model_for_task("fast")

                return await call_grok(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=model,
                    temperature=temperature,
                    session_id=session_id,
                    use_history=bool(session_id),
                )

        except Exception as e:
            logger.error(f"Error in grok_dispatch: {e}", exc_info=True)

            # Fallback de sécurité
            system_prompt = build_system_prompt(task_type="dispatch")
            return await call_grok(
                prompt=f"[DISPATCH ERROR] {prompt}\n\nError: {str(e)}",
                system_prompt=system_prompt + "\n\nL'utilisateur a rencontré une erreur de routing. Réponds normalement.",
                model=get_model_for_task("fast"),
                temperature=0.7,
                session_id=session_id,
            )
