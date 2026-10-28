"""
tools/grok_debate.py — Grok-Claude Bridge
Débat Grok ↔ Claude : tours en parallèle, arrêt dès qu'ils sont d'accord,
synthèse finale par un arbitre (Claude par défaut, ou Grok).
"""

from __future__ import annotations

import logging
from typing import Optional
from fastmcp import FastMCP

from context import build_system_prompt
from orchestration import DebateResult, run_debate

logger = logging.getLogger("grok-mcp-bridge.debate")

# Contexte Taranis complet (entités, vocabulaire) : sans lui, le débat attribuait
# des fûts à Querceo, qui n'en vend pas.
_DEFAULT_CONTEXT = build_system_prompt(
    task_type="dispatch",
    extra_instructions=(
        "Tu participes à un débat structuré. Sois précis, concis, orienté impact métier "
        "(fûts, spiritueux vieillis, marchés). Construis sur les arguments de l'autre "
        "plutôt que de répéter. Respecte strictement le rôle de chaque entité du groupe."
    ),
)


def format_debate(result: DebateResult, prompt: str, judge: str) -> str:
    lines = [
        "# 🥊 Débat Grok ↔ Claude",
        f"**Sujet :** {prompt}",
        f"**Tours :** {result.turns_done}" + (" — accord atteint" if result.converged else ""),
        f"**Modèles :** {result.grok_model or '—'} vs {result.claude_model or '—'}",
    ]
    if result.error:
        lines.append(f"\n⚠️ **Avertissement :** {result.error}")
    lines.append(f"\n## 🏁 Synthèse ({judge}, `{result.judge_model or '—'}`)\n\n{result.synthesis or '—'}")
    lines.append("\n---\n\n## Transcription")
    for entry in result.history:
        lines.append(f"\n### {entry['speaker']} — tour {entry['turn']}\n\n{entry['content']}")
    return "\n".join(lines)


async def debate_report(
    prompt: str,
    turns: Optional[int] = None,
    topic_context: Optional[str] = None,
    temperature: float = 0.7,
    judge: str = "claude",
) -> str:
    """Débat complet mis en forme — utilisé aussi par les tâches de fond."""
    result = await run_debate(prompt, turns=turns, topic_context=topic_context or _DEFAULT_CONTEXT,
                              temperature=temperature, judge=judge)
    return format_debate(result, prompt, judge)


def register_debate(mcp: FastMCP) -> None:
    """Enregistre le tool grok_debate sur l'instance FastMCP."""

    @mcp.tool(
        name="grok_debate",
        description=(
            "Débat Grok (xAI) ↔ Claude (Anthropic) sur une question ouverte. "
            "Tour 1 : chacun répond indépendamment, en parallèle. Tours suivants : chacun répond à l'autre. "
            "Le débat s'arrête dès que les deux se déclarent d'accord. "
            "Un arbitre (judge = claude | grok) rédige la synthèse : accords, désaccords, recommandation. "
            "turns : 1 à 4 (défaut 2). Pour 3-4 tours, préférer grok_start_job(kind='debate')."
        ),
    )
    async def grok_debate(
        prompt: str,
        turns: Optional[int] = None,
        topic_context: Optional[str] = None,
        temperature: float = 0.7,
        judge: str = "claude",
    ) -> str:
        logger.info("grok_debate | prompt_len=%d | turns=%s | judge=%s", len(prompt), turns, judge)
        try:
            return await debate_report(prompt, turns, topic_context, temperature, judge)
        except Exception as exc:
            logger.error("grok_debate: erreur inattendue: %s", exc, exc_info=True)
            return f"❌ **Erreur debate** : {exc}"
