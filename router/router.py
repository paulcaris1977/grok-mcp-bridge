"""
router/router.py — Grok-Claude Bridge
Router existant conservé à l'identique.
AJOUTS : dataclasses ChatRequest / ChatResponse + fonction run_debate().
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("grok-mcp-bridge.router")


# ══════════════════════════════════════════════════════════════════════════════
# EXISTANT — inchangé
# ══════════════════════════════════════════════════════════════════════════════

class TaskType(str, Enum):
    DISPATCH = "dispatch"
    CRITIQUE = "critique"
    CODE_TEST = "code_test"
    RESEARCH  = "research"
    DEBATE    = "debate"     # ← seul ajout dans l'enum


@dataclass
class RouteDecision:
    task_type:  TaskType
    confidence: float
    reasoning:  str


_CRITIQUE_PATTERNS = [
    (r"\b(critique|critiqu|review|audit|analyse critique|évaluation critique)\b", 2.0),
    (r"\b(risque|risk|faiblesse|danger|faille|problème majeur)\b",               2.2),
    (r"\b(stratégie|strategy|business plan|décision|que penses-tu|ton avis)\b",  1.6),
    (r"\b(améliorer|optimiser|recommandation|points faibles)\b",                 1.3),
]

_CODE_TEST_PATTERNS = [
    (r"\b(debug|débug|fix|corrige|bug|erreur|traceback|exception|TypeError)\b",  2.5),
    (r"\b(test|tester|pytest|unittest|run|exécute|lance)\b",                     1.8),
    (r"```(python|py|javascript|js|bash|sql)",                                   2.8),
    (r"\b(def |class |import |function |pip install|npm)\b",                     1.4),
]

_RESEARCH_PATTERNS = [
    (r"\b(recherche|search|veille|trouve|cherche|market|marché|tendance)\b",          1.8),
    (r"\b(prix|price|tarif|cours|évolution|trend|concurrent|competitor)\b",           2.0),
    (r"\b(202[5-6]|actualité|news|récent)\b",                                         1.5),
    (r"\b(distillerie|distillery|cooperage|whisky|whiskey|bourbon|scotch)\b",         1.7),
    (r"\b(fût|fûts|barrique|barriques|cask|casks|tonnelier|tonnellerie|maturation)\b",2.2),
]


def _score_patterns(text: str, patterns: list[tuple[str, float]]) -> float:
    text_lower   = text.lower()
    total_score  = 0.0
    max_possible = 0.0
    for pattern, weight in patterns:
        max_possible += weight
        if re.search(pattern, text_lower):
            total_score += weight
    return total_score / max_possible if max_possible > 0 else 0.0


def route(prompt: str, explicit_task: Optional[str] = None) -> RouteDecision:
    """Décide du meilleur handler. Debate jamais auto-routé (tool explicite uniquement)."""

    if explicit_task:
        mapping = {
            "critique": TaskType.CRITIQUE,
            "review":   TaskType.CRITIQUE,
            "code":     TaskType.CODE_TEST,
            "test":     TaskType.CODE_TEST,
            "debug":    TaskType.CODE_TEST,
            "research": TaskType.RESEARCH,
            "search":   TaskType.RESEARCH,
            "market":   TaskType.RESEARCH,
            # "debate" volontairement absent : passe toujours par grok_debate explicite
        }
        task = mapping.get(explicit_task.lower().strip())
        if task:
            logger.info("Explicit routing → %s", task.value)
            return RouteDecision(task_type=task, confidence=1.0,
                                 reasoning=f"Routing explicite : {explicit_task}")

    scores = {
        TaskType.CRITIQUE: _score_patterns(prompt, _CRITIQUE_PATTERNS),
        TaskType.CODE_TEST: _score_patterns(prompt, _CODE_TEST_PATTERNS),
        TaskType.RESEARCH:  _score_patterns(prompt, _RESEARCH_PATTERNS),
    }

    best_task  = max(scores, key=lambda t: scores[t])
    best_score = scores[best_task]

    if best_score >= 0.45:
        return RouteDecision(
            task_type=best_task,
            confidence=round(best_score, 2),
            reasoning=f"Auto-routing fort ({best_task.value} = {best_score:.2f})",
        )
    return RouteDecision(
        task_type=TaskType.DISPATCH,
        confidence=0.65,
        reasoning=f"Aucun signal fort (max={best_score:.2f}) → dispatch générique",
    )


# ══════════════════════════════════════════════════════════════════════════════
# NOUVEAU — mode debate bi-directionnel Grok ↔ Claude
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ChatRequest:
    """Paramètres d'une session debate."""
    prompt:        str
    turns:         int   = 2      # cohérent avec DEBATE_MAX_TURNS dans config.py
    topic_context: str   = ""     # contexte métier optionnel injecté en system prompt
    temperature:   float = 0.7
    max_tokens:    int   = 1024


@dataclass
class ChatResponse:
    """Résultat structuré d'une session debate."""
    final_answer:  str                        # dernière réponse (Claude, dernier à parler)
    full_history:  list[dict[str, str]]       # historique complet avec préfixes [Grok]/[Claude]
    turns_done:    int                        # tours réellement effectués
    grok_model:    str = ""
    claude_model:  str = ""
    error:         str = ""                   # non-vide si le debate a échoué partiellement


def _truncate_messages(messages: list[dict], keep: int) -> list[dict]:
    """
    Garde le(s) message(s) system + les `keep` derniers messages non-system.
    Garantit que le 1er message non-system est toujours 'user' (contrainte Anthropic).

    Cas défensif : si après troncature + strip des assistant initiaux la liste
    est vide, on réinsère le premier 'user' original comme ancre —
    sans ça l'API Anthropic rejette avec 400.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs  = [m for m in messages if m.get("role") != "system"]
    truncated   = other_msgs[-keep:] if len(other_msgs) > keep else other_msgs

    # Retirer les messages assistant en tête (Anthropic exige user en premier)
    while truncated and truncated[0]["role"] != "user":
        truncated = truncated[1:]

    # Garde-fou : si on a tout supprimé, ancrer sur le 1er user original
    if not truncated:
        first_user = next((m for m in other_msgs if m["role"] == "user"), None)
        if first_user:
            truncated = [first_user]

    return system_msgs + truncated


async def run_debate(request: ChatRequest) -> ChatResponse:
    """
    Orchestre une conversation multi-turns alternée Grok ↔ Claude.
    Protections prod Railway :
      - Timeout global asyncio.wait_for (DEBATE_TIMEOUT_S)
      - Troncature historique par tour (DEBATE_HISTORY_KEEP messages récents)
    """
    import asyncio
    from llm_clients import grok_chat, claude_chat
    from config import DEBATE_MAX_TOKENS, DEBATE_HISTORY_KEEP, DEBATE_TIMEOUT_S, DEBATE_MAX_TOTAL_TOKENS

    async def _inner() -> ChatResponse:
        history: list[dict[str, str]] = []
        grok_model_used   = ""
        claude_model_used = ""
        last_claude_reply = ""
        total_tokens_est  = 0  # estimation cumulative : len(content) / 4 ≈ tokens

        base_context = request.topic_context or (
            "Tu participes à un débat structuré entre Grok (xAI) et Claude (Anthropic). "
            "Sois précis, concis et construis sur les arguments du tour précédent."
        )
        grok_system = (
            f"{base_context}\n\nTu es Grok (xAI). Tu réponds en premier à chaque tour. "
            "Sois direct, créatif, sans filtre excessif. "
            "Construis sur ce que Claude a dit au tour précédent si disponible."
        )
        claude_system = (
            f"{base_context}\n\nTu es Claude (Anthropic). Tu réponds après Grok à chaque tour. "
            "Analyse rigoureusement l'argument de Grok, structure ta réponse, "
            "converge vers une synthèse si pertinent."
        )

        grok_messages:   list[dict] = [{"role": "system", "content": grok_system},
                                        {"role": "user",   "content": request.prompt}]
        claude_messages: list[dict] = [{"role": "system", "content": claude_system},
                                        {"role": "user",   "content": request.prompt}]
        max_tokens = request.max_tokens or DEBATE_MAX_TOKENS

        for turn in range(1, request.turns + 1):
            logger.info("Debate tour %d/%d", turn, request.turns)

            # Troncature avant chaque appel — évite l'explosion du context window
            grok_msgs_call   = _truncate_messages(grok_messages,   DEBATE_HISTORY_KEEP)

            # ── Appel Grok ───────────────────────────────────────────────────
            try:
                grok_reply, grok_model_used = await grok_chat(
                    grok_msgs_call, temperature=request.temperature, max_tokens=max_tokens)
            except Exception as exc:
                logger.error("Debate Grok tour %d: %s", turn, exc)
                return ChatResponse(
                    final_answer=last_claude_reply or f"Debate interrompu tour {turn} (Grok): {exc}",
                    full_history=history, turns_done=turn - 1,
                    grok_model=grok_model_used, claude_model=claude_model_used,
                    error=f"Grok tour {turn}: {exc}")

            grok_prefixed = f"[Grok — Tour {turn}]\n{grok_reply}"
            history.append({"role": "grok", "turn": str(turn), "content": grok_prefixed})

            # Troncature messages Claude + ajout réponse Grok comme "user"
            claude_msgs_call = _truncate_messages(
                claude_messages + [{"role": "user", "content": grok_prefixed}],
                DEBATE_HISTORY_KEEP)

            # ── Appel Claude ─────────────────────────────────────────────────
            try:
                claude_reply, claude_model_used = await claude_chat(
                    claude_msgs_call, temperature=request.temperature, max_tokens=max_tokens)
            except Exception as exc:
                logger.error("Debate Claude tour %d: %s", turn, exc)
                return ChatResponse(
                    final_answer=grok_reply, full_history=history, turns_done=turn,
                    grok_model=grok_model_used, claude_model=claude_model_used,
                    error=f"Claude tour {turn}: {exc}")

            claude_prefixed   = f"[Claude — Tour {turn}]\n{claude_reply}"
            last_claude_reply = claude_reply
            history.append({"role": "claude", "turn": str(turn), "content": claude_prefixed})

            # Enrichissement pour le tour suivant (historique complet, la troncature s'en charge)
            grok_messages.append({"role": "assistant", "content": grok_reply})
            grok_messages.append({"role": "user",      "content": claude_prefixed})
            claude_messages.append({"role": "user",      "content": grok_prefixed})
            claude_messages.append({"role": "assistant", "content": claude_reply})

            # Garde-fou coût : estimation tokens cumulés (len/4 ≈ tokens)
            total_tokens_est += (len(grok_reply) + len(claude_reply)) // 4
            logger.info("Debate tour %d OK — Grok:%d chars Claude:%d chars (~%d tokens cumulés)",
                        turn, len(grok_reply), len(claude_reply), total_tokens_est)
            if total_tokens_est >= DEBATE_MAX_TOTAL_TOKENS:
                logger.warning("Debate: plafond tokens atteint (%d >= %d), arrêt anticipé.",
                               total_tokens_est, DEBATE_MAX_TOTAL_TOKENS)
                return ChatResponse(
                    final_answer=last_claude_reply,
                    full_history=history, turns_done=turn,
                    grok_model=grok_model_used, claude_model=claude_model_used,
                    error=f"Plafond tokens atteint (~{total_tokens_est} tokens estimés)")

        return ChatResponse(
            final_answer=last_claude_reply, full_history=history,
            turns_done=request.turns, grok_model=grok_model_used,
            claude_model=claude_model_used)

    # ── Timeout global : protège Railway des débats trop longs ───────────────
    try:
        return await asyncio.wait_for(_inner(), timeout=DEBATE_TIMEOUT_S)
    except asyncio.TimeoutError:
        logger.error("run_debate: timeout global %.0fs dépassé", DEBATE_TIMEOUT_S)
        return ChatResponse(
            final_answer="⏱️ Le débat a dépassé la limite de temps Railway (90s). "
                         "Réduisez le nombre de turns ou DEBATE_MAX_TOKENS.",
            full_history=[], turns_done=0,
            error=f"Timeout global {DEBATE_TIMEOUT_S}s")
