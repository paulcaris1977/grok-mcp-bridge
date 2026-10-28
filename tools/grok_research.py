"""
tools/grok_research.py
Recherche web et X en temps réel via les outils serveur xAI (web_search, x_search).
Les sources citées par xAI sont listées sous la réponse.
Optimisé pour le secteur tonnellerie/spiritueux et les marchés Taranis.
"""

import logging
from typing import Optional
from fastmcp import FastMCP

from grok_client import call_grok, search_tools
from context import build_system_prompt

logger = logging.getLogger("grok-mcp-bridge.research")

_RESEARCH_PROMPT_TEMPLATE = """
Effectue une recherche sur le sujet suivant, avec les outils de recherche à ta disposition.
Appuie chaque fait et chaque chiffre sur une source trouvée pendant cette recherche.
Si tu ne trouves pas une information, dis-le au lieu de l'estimer.

SUJET : {query}

{market_section}

STRUCTURE DE TA RÉPONSE :

## 📊 Synthèse

[Résumé des informations clés en 3-5 phrases]

## 🔑 Points essentiels

[Liste des faits importants, datés, avec leur source]

## 🌍 Implications pour Taranis

[Impact direct sur les marchés / clients / opérations Taranis]

## 📈 Opportunités détectées

[Opportunités commerciales ou stratégiques identifiées]

## ⚠️ Risques ou vigilance

[Éléments à surveiller]
""".strip()

# Effort low : réponse courte, sans la structure en 5 rubriques
_QUICK_PROMPT_TEMPLATE = """
Recherche rapide, réponse courte et directe (quelques phrases), sources à l'appui.
Si tu ne trouves pas l'information, dis-le.

SUJET : {query}

{market_section}
""".strip()

# Compatibilité : l'ancien paramètre depth se traduit en effort
_DEPTH_TO_EFFORT = {"quick": "low", "standard": "medium", "deep": "high"}


def register_research(mcp: FastMCP) -> None:
    """Enregistre le tool grok_research sur l'instance FastMCP."""

    @mcp.tool()
    async def grok_research(
        query: str,
        market: Optional[str] = None,
        depth: str = "standard",
        session_id: Optional[str] = None,
        effort: Optional[str] = None,
        sources: str = "web+x",
        model: Optional[str] = None,
    ) -> str:
        """
        Recherche web et X en temps réel via Grok, avec sources citées.

        Idéal pour : veille concurrentielle, prix marché, actualités distilleries,
        tendances spiritueux, informations sur des clients potentiels,
        ce qui se dit sur X d'une marque ou d'un sujet.

        Args:
            query: Sujet à rechercher.
            market: Marché cible pour contextualiser (Japan, Korea, Scotland,
                    Ireland, France, LATAM, India, Georgia, China).
            depth: Ancien réglage, conservé : quick | standard | deep
                   (= effort low | medium | high). Ignoré si effort est donné.
            session_id: ID de session pour suivi de recherche multi-turns.
            effort: low | medium | high | max. Règle modèle, profondeur de
                    raisonnement, nombre de recherches et longueur.
            sources: web | x | web+x (défaut web+x).
            model: Force un modèle xAI précis (ex. grok-4.7) au lieu du profil.

        Returns:
            Rapport structuré avec implications Taranis, sources et coût estimé.
        """
        return await _run_research(
            query,
            market=market,
            depth=depth,
            session_id=session_id,
            effort=effort,
            sources=sources,
            model=model,
        )


def research_prompts(query: str, market: Optional[str], effort: str) -> tuple[str, str]:
    """(system, prompt) d'une recherche — réutilisé par grok_verify."""
    market_section = ""
    if market:
        market_section = f"MARCHÉ CIBLE : {market}\nAdapte l'analyse aux spécificités de ce marché.\n"
    template = _QUICK_PROMPT_TEMPLATE if effort == "low" else _RESEARCH_PROMPT_TEMPLATE
    prompt = template.format(query=query, market_section=market_section)
    return build_system_prompt(task_type="research"), prompt


async def _run_research(
    query: str,
    market: Optional[str] = None,
    depth: str = "standard",
    session_id: Optional[str] = None,
    temperature: float = 0.5,
    effort: Optional[str] = None,
    sources: str = "web+x",
    model: Optional[str] = None,
) -> str:
    """Implémentation interne, appelable depuis grok_dispatch."""
    effort = effort or _DEPTH_TO_EFFORT.get(depth, "medium")
    system_prompt, prompt = research_prompts(query, market, effort)

    logger.info(
        f"Running research | effort={effort} | sources={sources} | "
        f"model={model or 'profil'} | market={market or 'all'} | query_len={len(query)}"
    )

    return await call_grok(
        prompt=prompt,
        system_prompt=system_prompt,
        model=model,
        temperature=temperature,
        session_id=session_id,
        use_history=bool(session_id),
        effort=effort,
        tools=search_tools(sources),
    )
