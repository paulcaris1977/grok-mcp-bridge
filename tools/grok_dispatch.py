"""
tools/grok_dispatch.py
Tool principal et point d'entrée unique recommandé pour Claude.
L'appelant choisit le mode ; plus de routage par mots-clés.
"""

import logging
from typing import Optional
from fastmcp import FastMCP

from grok_client import call_grok
from router.router import Mode, MODE_HELP, resolve_mode
from context import build_system_prompt

logger = logging.getLogger("grok-mcp-bridge.dispatch")


def register_dispatch(mcp: FastMCP) -> None:
    """Enregistre le tool principal de dispatch."""

    @mcp.tool(
        name="grok_dispatch",
        description=(
            "Point d'entrée unique vers Grok. Choisis le mode selon la demande : "
            + MODE_HELP + " (défaut general). "
            "effort = low | medium | high | max (rapidité/coût contre profondeur) ; "
            "model force un modèle xAI précis."
        )
    )
    async def grok_dispatch(
        prompt: str,
        mode: Optional[str] = None,           # general | critique | code | research
        task: Optional[str] = None,           # ancien nom de mode, toujours accepté
        session_id: Optional[str] = None,
        temperature: float = 0.7,
        effort: Optional[str] = None,          # None = défaut du handler (code : high, sinon medium)
        model: Optional[str] = None,
    ) -> str:
        """
        Point d'entrée principal pour Claude.
        mode choisit le handler ; task (ancien paramètre) reste accepté.
        """
        # Ne transmettre effort/model que s'ils sont fournis : chaque handler garde son défaut
        tuning = {k: v for k, v in {"effort": effort, "model": model}.items() if v}
        try:
            selected = resolve_mode(mode, task)
            logger.info(f"grok_dispatch → mode '{selected.value}'")

            # ── Délégation aux handlers spécialisés ─────────────────────
            if selected == Mode.CRITIQUE:
                from tools.grok_critique import _run_critique
                return await _run_critique(
                    content=prompt,
                    session_id=session_id,
                    temperature=temperature,
                    **tuning,
                )

            elif selected == Mode.CODE:
                from tools.grok_code_test import _run_code_test
                return await _run_code_test(
                    code=prompt,                    # fallback simple
                    language="python",
                    context="Code envoyé via grok_dispatch",
                    session_id=session_id,
                    temperature=min(temperature, 0.3),   # plus basse pour du code
                    **tuning,
                )

            elif selected == Mode.RESEARCH:
                from tools.grok_research import _run_research
                return await _run_research(
                    query=prompt,
                    session_id=session_id,
                    temperature=temperature,
                    **tuning,
                )

            # ── Cas par défaut (question générale) ─────────────────────
            else:
                system_prompt = build_system_prompt(task_type="dispatch")

                return await call_grok(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    model=model,
                    temperature=temperature,
                    session_id=session_id,
                    use_history=bool(session_id),
                    effort=effort,
                )

        except Exception as e:
            logger.error(f"Error in grok_dispatch: {e}", exc_info=True)

            # Pas de second appel Grok : il masquait l'erreur et doublait le coût
            return f"❌ Erreur grok_dispatch ({type(e).__name__}) : {e}"
