"""
tools/grok_debate.py — Grok-Claude Bridge
Tool MCP exposant le mode debate bi-directionnel Grok ↔ Claude.
Accessible uniquement via appel explicite (jamais auto-routé depuis grok_dispatch).
"""

from __future__ import annotations

import logging
from typing import Optional
from fastmcp import FastMCP

from router.router import ChatRequest, run_debate

logger = logging.getLogger("grok-mcp-bridge.debate")


def register_debate(mcp: FastMCP) -> None:
    """Enregistre le tool grok_debate sur l'instance FastMCP."""

    @mcp.tool(
        name="grok_debate",
        description=(
            "Lance un débat bi-directionnel multi-turns entre Grok (xAI) et Claude (Anthropic). "
            "Chaque tour : Grok répond en premier, Claude analyse et synthétise. "
            "Idéal pour explorer une question sous deux angles complémentaires : "
            "Grok (créativité, web temps réel, sans filtre) vs Claude (rigueur, structure, éthique). "
            "Retourne l'historique complet avec préfixes [Grok]/[Claude] + synthèse finale."
        ),
    )
    async def grok_debate(
        prompt: str,
        turns: int = 2,
        topic_context: Optional[str] = None,
        temperature: float = 0.7,
    ) -> str:
        turns = max(1, min(turns, 6))

        # Contexte debate dédié — plus pertinent que le prompt dispatch générique
        effective_context = topic_context or (
            "Tu participes à un débat structuré pour Taranis Cooperage Group "
            "(tonnellerie internationale : B'Oak, Dair'nua, Alba, Querceo). "
            "Sois précis, concis, orienté impact métier (fûts, spiritueux vieillis, marchés). "
            "Construis sur les arguments du tour précédent plutôt que de répéter."
        )

        logger.info("grok_debate | prompt_len=%d | turns=%d | temp=%.2f",
                    len(prompt), turns, temperature)

        request = ChatRequest(
            prompt=prompt,
            turns=turns,
            topic_context=effective_context,
            temperature=temperature,
        )

        try:
            response = await run_debate(request)
        except Exception as exc:
            logger.error("grok_debate: erreur inattendue: %s", exc, exc_info=True)
            return (
                f"❌ **Erreur debate** : {exc}\n\n"
                "Le debate n'a pas pu démarrer. "
                "Vérifiez que ANTHROPIC_API_KEY et XAI_API_KEY sont bien configurées dans Railway."
            )

        # ── Formatage de la réponse ───────────────────────────────────────────
        lines: list[str] = []

        lines.append(f"# 🥊 Debate Grok ↔ Claude")
        lines.append(f"**Sujet :** {prompt}")
        lines.append(f"**Tours effectués :** {response.turns_done}/{turns}")
        lines.append(f"**Modèles :** {response.grok_model} vs {response.claude_model}")

        if response.error:
            lines.append(f"\n⚠️ **Avertissement :** {response.error}")

        lines.append("\n---\n")

        # Historique complet
        for entry in response.full_history:
            lines.append(entry["content"])
            lines.append("\n---\n")

        # Synthèse finale
        lines.append("## 🏁 Synthèse finale (Claude)")
        lines.append(response.final_answer)

        return "\n".join(lines)
