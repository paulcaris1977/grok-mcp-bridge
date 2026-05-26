"""
tools/grok_research.py
Recherche web et market intelligence via Grok avec Live Search.
Optimisé pour le secteur tonnellerie/spiritueux et les marchés Taranis.
"""

import logging
from typing import Optional
from fastmcp import FastMCP

from grok_client import call_grok, get_model_for_task
from context import build_system_prompt

logger = logging.getLogger("grok-mcp-bridge.research")

_RESEARCH_PROMPT_TEMPLATE = """
Effectue une recherche approfondie sur le sujet suivant.

SUJET : {query}

{market_section}

STRUCTURE DE TA RÉPONSE :

## 📊 Synthèse

[Résumé des informations clés en 3-5 phrases]

## 🔑 Points essentiels

[Liste des faits importants avec sources et dates quand disponibles]

## 🌍 Implications pour Taranis

[Impact direct sur les marchés / clients / opérations Taranis]

## 📈 Opportunités détectées

[Opportunités commerciales ou stratégiques identifiées]

## ⚠️ Risques ou vigilance

[Éléments à surveiller]

## 📚 Sources

[Liens ou références utilisées]
""".strip()


def register_research(mcp: FastMCP) -> None:
    """Enregistre le tool grok_research sur l'instance FastMCP."""

    @mcp.tool()
    async def grok_research(
        query: str,
        market: Optional[str] = None,
        depth: str = "standard",
        session_id: Optional[str] = None,
    ) -> str:
        """
        Recherche web et analyse de marché via Grok avec accès temps réel.
        
        Idéal pour : veille concurrentielle, prix marché, actualités distilleries,
        tendances spiritueux, informations sur des clients potentiels.
        
        Args:
            query: Sujet à rechercher.
            market: Marché cible pour contextualiser (Japan, Korea, Scotland,
                    Ireland, France, LATAM, India).
            depth: Niveau de profondeur : 'quick' (résumé rapide) | 'standard' |
                   'deep' (analyse exhaustive).
            session_id: ID de session pour suivi de recherche multi-turns.
        
        Returns:
            Rapport structuré avec implications Taranis et sources.
        """
        return await _run_research(
            query,
            market=market,
            depth=depth,
            session_id=session_id,
        )


async def _run_research(
    query: str,
    market: Optional[str] = None,
    depth: str = "standard",
    session_id: Optional[str] = None,
    temperature: float = 0.5,
) -> str:
    """Implémentation interne, appelable depuis grok_dispatch."""
    market_section = ""
    if market:
        market_section = f"MARCHÉ CIBLE : {market}\nAdapte l'analyse aux spécificités de ce marché.\n"

    # Ajuste les tokens selon la profondeur
    token_map = {"quick": 1024, "standard": 2048, "deep": 4096}
    max_tokens = token_map.get(depth, 2048)

    # Ajuste la température pour les recherches rapides
    temp = 0.3 if depth == "quick" else temperature

    system_prompt = build_system_prompt(task_type="research")
    prompt = _RESEARCH_PROMPT_TEMPLATE.format(
        query=query,
        market_section=market_section,
    )
    model = get_model_for_task("research")

    logger.info(
        f"Running research | model={model} | depth={depth} | "
        f"market={market or 'all'} | query_len={len(query)}"
    )

    return await call_grok(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=temp,
        max_tokens=max_tokens,
        session_id=session_id,
        use_history=bool(session_id),
    )
