"""
orchestration.py — Grok-Claude Bridge
Schémas multi-étapes nommés :
  - run_verify      : Grok cherche avec sources, Claude contrôle chaque affirmation.
  - run_cross_check : même question à Grok et Claude en parallèle, puis comparaison.
  - run_debate      : tours en parallèle, arrêt sur accord, synthèse par un arbitre.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from config import (
    DEBATE_MAX_TOKENS, DEBATE_HISTORY_KEEP, DEBATE_TIMEOUT_S,
    DEBATE_MAX_TOTAL_TOKENS, DEBATE_MAX_TURNS,
)
from context import build_system_prompt
from grok_client import grok_respond, search_tools
from llm_clients import claude_chat, claude_respond, grok_chat

logger = logging.getLogger("grok-mcp-bridge.orchestration")

CLAUDE_TIMEOUT_S = 90.0
_JUDGES = ("claude", "grok")


async def _judge(judge: str, system: str, prompt: str, max_tokens: int = 2000) -> tuple[str, str]:
    """Appel d'arbitrage → (texte, modèle). Grok arbitre en effort medium, sans recherche."""
    if judge == "grok":
        result = await grok_respond(
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            effort="medium", max_output_tokens=max_tokens * 2)
        return result.text, result.model
    return await claude_chat(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        max_tokens=max_tokens, effort="medium", timeout=CLAUDE_TIMEOUT_S)


def _claude_effort_for(effort: str) -> str:
    """Effort du bridge (low/medium/high/max) → effort Claude ; low reste low, le reste est plafonné à high."""
    return "low" if effort == "low" else ("medium" if effort == "medium" else "high")


def _check_judge(judge: str) -> str:
    judge = (judge or "claude").strip().lower()
    if judge not in _JUDGES:
        raise ValueError(f"arbitre inconnu '{judge}' (valeurs : claude, grok)")
    return judge


# ══════════════════════════════════════════════════════════════════════════════
# VERIFY — recherche Grok, contrôle Claude
# ══════════════════════════════════════════════════════════════════════════════

_VERIFY_SYSTEM = """
Tu contrôles un rapport de recherche produit par Grok, avec ses sources web citées.
Tu n'as accès ni au web ni au contenu des pages : tu juges
(1) si chaque chiffre ou fait important est rattaché à une source citée,
(2) sa plausibilité au regard de tes connaissances,
(3) les contradictions internes du rapport.
Ne réécris pas le rapport. N'invente aucun chiffre de remplacement.

Format :
| # | Affirmation | Source | Verdict | Commentaire |
Verdicts : ✅ sourcé et plausible · ⚠️ non sourcé ou invérifiable · ❌ douteux ou contredit.
Puis « Fiabilité globale : x/5 » et « À vérifier en priorité » (3 lignes max).
Réponds en français.
""".strip()


async def run_verify(
    query: str,
    market: Optional[str] = None,
    effort: str = "medium",
    sources: str = "web+x",
) -> str:
    from tools.grok_research import research_prompts

    system, prompt = research_prompts(query, market, effort)
    grok = await grok_respond(
        [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        effort=effort, tools=search_tools(sources))
    report = grok.render(footer=False)

    try:
        claude = await claude_respond(
            [{"role": "system", "content": _VERIFY_SYSTEM},
             {"role": "user", "content": f"RAPPORT À CONTRÔLER :\n\n{report}"}],
            max_tokens=4000, effort="medium", timeout=CLAUDE_TIMEOUT_S)
        check, claude_footer = claude.text, claude.footer()
    except Exception as exc:
        logger.error("verify: contrôle Claude en échec: %s", exc)
        check, claude_footer = f"⚠️ Contrôle Claude indisponible : {exc}", "—"

    return (
        f"# 🔎 Recherche Grok\n\n{report}\n\n"
        f"# ✅ Contrôle Claude\n\n{check}\n\n---\n"
        f"Grok {grok.footer()} · contrôle Claude {claude_footer}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# CROSS-CHECK — deux réponses indépendantes, puis comparaison
# ══════════════════════════════════════════════════════════════════════════════

_COMPARE_SYSTEM = """
Tu compares deux réponses INDÉPENDANTES à la même question : A (Grok) et B (Claude).
Sections, dans cet ordre :
## Accords
## Désaccords (pour chacun : qui a probablement raison et pourquoi, ou « indécidable »)
## Ce qu'une seule des deux mentionne
## À vérifier
## Réponse consolidée (courte, sans ajouter de fait absent des deux réponses)
Réponds en français.
""".strip()


async def run_cross_check(
    question: str,
    effort: str = "medium",
    sources: Optional[str] = None,
    judge: str = "claude",
) -> str:
    judge = _check_judge(judge)
    system = build_system_prompt(task_type="dispatch")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": question}]

    grok_res, claude_res = await asyncio.gather(
        grok_respond(messages, effort=effort, tools=search_tools(sources) if sources else None),
        claude_respond(messages, max_tokens=4000, effort=_claude_effort_for(effort), timeout=CLAUDE_TIMEOUT_S),
        return_exceptions=True,
    )

    if isinstance(grok_res, Exception) and isinstance(claude_res, Exception):
        return f"❌ Les deux appels ont échoué.\nGrok : {grok_res}\nClaude : {claude_res}"
    if isinstance(grok_res, Exception):
        return f"⚠️ Grok en échec ({grok_res}) — réponse de Claude seule :\n\n{claude_res.text}"
    if isinstance(claude_res, Exception):
        return f"⚠️ Claude en échec ({claude_res}) — réponse de Grok seule :\n\n{grok_res.render()}"

    grok_text = grok_res.render(footer=False)
    claude_text, claude_model = claude_res.text, claude_res.model
    comparison, judge_model = await _judge(
        judge, _COMPARE_SYSTEM,
        f"QUESTION :\n{question}\n\n=== A (Grok) ===\n{grok_text}\n\n=== B (Claude) ===\n{claude_text}")

    return (
        f"# ⚖️ Contre-expertise Grok × Claude\n**Question :** {question}\n"
        f"**Arbitre :** {judge} (`{judge_model}`)\n\n{comparison}\n\n---\n\n"
        f"<details><summary>Réponse Grok</summary>\n\n{grok_text}\n\n</details>\n\n"
        f"<details><summary>Réponse Claude (`{claude_model}`)</summary>\n\n{claude_text}\n\n</details>\n\n"
        f"---\nGrok {grok_res.footer()} · Claude {claude_res.footer()}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# DEBATE — tours en parallèle, arrêt sur accord, synthèse par l'arbitre
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class DebateResult:
    history: list[dict[str, str]] = field(default_factory=list)   # {speaker, turn, content}
    turns_done: int = 0
    converged: bool = False
    synthesis: str = ""
    judge_model: str = ""
    grok_model: str = ""
    claude_model: str = ""
    error: str = ""


_VERDICT_INSTRUCTION = (
    "Termine ta réponse par une dernière ligne seule : « ACCORD » si vous êtes "
    "désormais d'accord sur l'essentiel, sinon « DÉSACCORD »."
)


def _agrees(text: str) -> bool:
    lines = [l.strip().strip("*«»\" ").upper() for l in text.strip().splitlines() if l.strip()]
    return bool(lines) and lines[-1] == "ACCORD"


def _truncate_messages(messages: list[dict], keep: int) -> list[dict]:
    """Garde les messages system + les `keep` derniers ; le 1er non-system doit être 'user'."""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]
    truncated = other_msgs[-keep:] if len(other_msgs) > keep else other_msgs
    while truncated and truncated[0]["role"] != "user":
        truncated = truncated[1:]
    if not truncated:
        first_user = next((m for m in other_msgs if m["role"] == "user"), None)
        if first_user:
            truncated = [first_user]
    return system_msgs + truncated


_SYNTHESIS_SYSTEM = """
Tu es l'arbitre d'un débat entre Grok et Claude. À partir de la transcription :
## Accords
## Désaccords restants (positions de chacun)
## Recommandation (ta position nette, justifiée en 3-5 lignes)
Réponds en français, sans ajouter de fait absent du débat.
""".strip()


async def run_debate(
    prompt: str,
    turns: Optional[int] = None,
    topic_context: str = "",
    temperature: float = 0.7,
    judge: str = "claude",
) -> DebateResult:
    judge = _check_judge(judge)
    turns = max(1, min(turns or DEBATE_MAX_TURNS, 4))
    out = DebateResult()

    base = topic_context or "Tu participes à un débat structuré entre Grok (xAI) et Claude (Anthropic)."
    grok_msgs = [{"role": "system", "content": f"{base}\n\nTu es Grok (xAI). Sois direct et concret."},
                 {"role": "user", "content": prompt}]
    claude_msgs = [{"role": "system", "content": f"{base}\n\nTu es Claude (Anthropic). Sois rigoureux et structuré."},
                   {"role": "user", "content": prompt}]

    async def _turns() -> None:
        total_tokens = 0
        for turn in range(1, turns + 1):
            logger.info("Debate tour %d/%d", turn, turns)
            g, c = await asyncio.gather(
                grok_chat(_truncate_messages(grok_msgs, DEBATE_HISTORY_KEEP),
                          temperature=temperature, max_tokens=DEBATE_MAX_TOKENS),
                claude_chat(_truncate_messages(claude_msgs, DEBATE_HISTORY_KEEP),
                            max_tokens=DEBATE_MAX_TOKENS),
                return_exceptions=True)
            for name, res in (("Grok", g), ("Claude", c)):
                if isinstance(res, Exception):
                    out.error = f"{name} tour {turn}: {res}"
                    return
            (g_text, out.grok_model), (c_text, out.claude_model) = g, c
            out.history += [{"speaker": "Grok", "turn": str(turn), "content": g_text},
                            {"speaker": "Claude", "turn": str(turn), "content": c_text}]
            out.turns_done = turn

            if turn > 1 and _agrees(g_text) and _agrees(c_text):
                out.converged = True
                return
            total_tokens += (len(g_text) + len(c_text)) // 4
            if total_tokens >= DEBATE_MAX_TOTAL_TOKENS:
                out.error = f"Plafond tokens atteint (~{total_tokens} tokens estimés)"
                return

            # Tour suivant : chacun répond à l'autre (vu au même tour, en parallèle)
            grok_msgs.append({"role": "assistant", "content": g_text})
            grok_msgs.append({"role": "user", "content":
                              f"[Claude — tour {turn}]\n{c_text}\n\nRéponds-lui : ce qui te convainc, "
                              f"ce que tu contestes. {_VERDICT_INSTRUCTION}"})
            claude_msgs.append({"role": "assistant", "content": c_text})
            claude_msgs.append({"role": "user", "content":
                                f"[Grok — tour {turn}]\n{g_text}\n\nRéponds-lui : ce qui te convainc, "
                                f"ce que tu contestes. {_VERDICT_INSTRUCTION}"})

    try:
        await asyncio.wait_for(_turns(), timeout=DEBATE_TIMEOUT_S)
    except asyncio.TimeoutError:
        out.error = f"Timeout global {DEBATE_TIMEOUT_S:.0f}s après {out.turns_done} tour(s)"

    if out.history:
        transcript = "\n\n".join(f"[{h['speaker']} — tour {h['turn']}]\n{h['content']}" for h in out.history)
        try:
            out.synthesis, out.judge_model = await _judge(
                judge, _SYNTHESIS_SYSTEM, f"SUJET : {prompt}\n\nTRANSCRIPTION :\n{transcript}", max_tokens=1500)
        except Exception as exc:
            out.synthesis = f"⚠️ Synthèse indisponible : {exc}"
    return out
