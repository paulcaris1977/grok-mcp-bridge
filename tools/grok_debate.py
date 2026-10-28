"""
tools/grok_debate.py — Grok-Claude Bridge
Débat Grok ↔ Claude : tours en parallèle, arrêt dès qu'ils sont d'accord,
synthèse finale par un arbitre (Claude par défaut, ou Grok).
"""

from __future__ import annotations

import logging
from typing import Optional
from fastmcp import FastMCP

from orchestration import run_debate

logger = logging.getLogger("grok-mcp-bridge.debate")

_DEFAULT_CONTEXT = (
    "Tu participes à un débat structuré pour Taranis Cooperage Group "
    "(tonnellerie internationale : B'Oak, Dair'nua, Alba, Querceo). "
    "Sois précis, concis, orienté impact métier (fûts, spiritueux vieillis, marchés). "
    "Construis sur les arguments de l'autre plutôt que de répéter."
)


def register_debate(mcp: FastMCP) -> None:
    """Enregistre le tool grok_debate sur l'instance FastMCP."""

    @mcp.tool(
        name="grok_debate",
        description=(
            "Débat Grok (xAI) ↔ Claude (Anthropic) sur une question ouverte. "
            "Tour 1 : chacun répond indépendamment, en parallèle. Tours suivants : chacun répond à l'autre. "
            "Le débat s'arrête dès que les deux se déclarent d'accord. "
            "Un arbitre (judge = claude | grok) rédige la synthèse : accords, désaccords, recommandation. "
            "turns : 1 à 4 (défaut 2)."
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
            result = await run_debate(prompt, turns=turns, topic_context=topic_context or _DEFAULT_CONTEXT,
                                      temperature=temperature, judge=judge)
        except Exception as exc:
            logger.error("grok_debate: erreur inattendue: %s", exc, exc_info=True)
            return f"❌ **Erreur debate** : {exc}"

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
