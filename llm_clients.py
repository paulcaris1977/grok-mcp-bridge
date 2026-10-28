"""
llm_clients.py — Grok-Claude Bridge
Clients du mode debate bi-directionnel.
Grok passe par grok_client (client unique, Responses API) ; Claude par httpx direct.

Deux fonctions publiques :
  - grok_chat(messages, **kwargs)   → (content: str, model: str)
  - claude_chat(messages, **kwargs) → (content: str, model: str)
  - claude_respond(messages, **kwargs) → ClaudeResult (texte, tokens, coût estimé)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Union

import httpx

from grok_client import grok_respond
from config import (
    ANTHROPIC_API_KEY, CLAUDE_BASE_URL, CLAUDE_MODEL, CLAUDE_EFFORTS, CLAUDE_DEFAULT_EFFORT,
    CLAUDE_FALLBACK_MODELS, CLAUDE_PRICES,
    HTTP_TIMEOUT, HTTP_MAX_RETRIES, DEBATE_MAX_TOKENS,
)

logger = logging.getLogger("grok-mcp-bridge.llm_clients")

Message = dict[str, Any]  # {"role": "user"|"assistant"|"system", "content": str}


# ══════════════════════════════════════════════════════════════════════════════
# GROK  —  Responses API via grok_client (client unique)
# ══════════════════════════════════════════════════════════════════════════════

async def grok_chat(
    messages: list[Message],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.7,
) -> tuple[str, str]:
    """
    Appel Grok pour le debate — délègue au client unique (Responses API).
    Profil "low" (modèle sans raisonnement) : le budget DEBATE_MAX_TOKENS
    n'est pas consommé par du raisonnement et le débat tient dans DEBATE_TIMEOUT_S.
    Retourne (content, model_used).
    """
    result = await grok_respond(
        messages,
        effort="low",
        model=model,
        temperature=temperature,
        max_output_tokens=max_tokens or DEBATE_MAX_TOKENS,
        timeout_s=HTTP_TIMEOUT * (HTTP_MAX_RETRIES + 1),
    )
    return result.text, result.model


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE  —  Anthropic Messages API (POST /messages)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_system(messages: list[Message]) -> tuple[str, list[Message]]:
    """
    Sépare les messages 'system' du reste.
    Anthropic exige le champ 'system' à part, pas dans la liste messages.
    """
    system_parts: list[str] = []
    other: list[Message]    = []
    for msg in messages:
        if msg.get("role") == "system":
            system_parts.append(str(msg["content"]))
        else:
            other.append({"role": msg["role"], "content": str(msg["content"])})
    return "\n\n".join(system_parts), other


def claude_effort(effort: Optional[str]) -> str:
    effort = (effort or CLAUDE_DEFAULT_EFFORT).strip().lower()
    if effort not in CLAUDE_EFFORTS:
        raise ValueError(f"effort Claude inconnu '{effort}' (valeurs : {', '.join(CLAUDE_EFFORTS)})")
    return effort


def claude_schema(schema: Union[dict, str]) -> dict:
    """Valide le schéma → output_config.format (structured outputs Anthropic)."""
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except json.JSONDecodeError as exc:
            raise ValueError(f"schema n'est pas du JSON valide : {exc}") from exc
    if not isinstance(schema, dict) or "type" not in schema:
        raise ValueError("schema doit être un objet JSON Schema avec un champ 'type'")
    return {"type": "json_schema", "schema": schema}


@dataclass
class ClaudeResult:
    text: str
    model: str
    effort: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> Optional[float]:
        price = CLAUDE_PRICES.get(self.model)
        if not price:
            return None
        return (self.input_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000

    def footer(self) -> str:
        cost = self.cost_usd
        parts = [self.model, f"effort {self.effort}",
                 f"{self.input_tokens:,} → {self.output_tokens:,} tokens".replace(",", " "),
                 f"≈ {cost:.3f} $" if cost is not None else "coût inconnu"]
        return "`" + " · ".join(parts) + "`"


def _claude_messages(messages: list[Message]) -> tuple[str, list[Message]]:
    """System à part, 1er message user, alternance stricte user/assistant (fusion des doublons)."""
    system_prompt, filtered = _extract_system(messages)
    if not filtered or filtered[0]["role"] != "user":
        filtered.insert(0, {"role": "user", "content": "Commence."})
    merged: list[Message] = []
    for msg in filtered:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append({"role": msg["role"], "content": msg["content"]})
    return system_prompt, merged


async def claude_respond(
    messages: list[Message],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    effort: str | None = None,
    schema: Union[dict, str, None] = None,
    timeout: float | None = None,
) -> ClaudeResult:
    """
    Appel Claude via Anthropic Messages API, thinking adaptatif piloté par effort.
    schema → sortie JSON garantie (output_config.format).
    """
    _model  = model or CLAUDE_MODEL
    _effort = claude_effort(effort)
    system_prompt, merged = _claude_messages(messages)

    output_config: dict[str, Any] = {"effort": _effort}
    if schema is not None:
        output_config["format"] = claude_schema(schema)
    payload: dict[str, Any] = {
        "model":         _model,
        # le raisonnement compte dans max_tokens : plancher pour ne pas couper la réponse
        "max_tokens":    max(max_tokens or DEBATE_MAX_TOKENS, 2000),
        "messages":      merged,
        "output_config": output_config,
    }
    if system_prompt:
        payload["system"] = system_prompt

    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
    }
    if _model in CLAUDE_FALLBACK_MODELS:
        payload["fallbacks"] = "default"
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01"

    last_exc: Exception | None = None
    for attempt in range(HTTP_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout or HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{CLAUDE_BASE_URL}/messages",
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            stop = data.get("stop_reason")
            if stop == "refusal":
                category = (data.get("stop_details") or {}).get("category")
                raise ValueError(f"Claude a décliné la demande (catégorie : {category or 'non précisée'})")
            content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            if not content:
                raise ValueError(f"Claude: réponse sans texte (stop_reason={stop}) — "
                                 "augmenter max_tokens ou baisser effort")
            usage = data.get("usage") or {}
            result = ClaudeResult(
                text=content, model=data.get("model", _model), effort=_effort,
                input_tokens=(usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
                              + usage.get("cache_creation_input_tokens", 0)),
                output_tokens=usage.get("output_tokens", 0))
            logger.debug("claude_respond [%s] → %d chars", result.model, len(content))
            return result

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < HTTP_MAX_RETRIES:
                logger.warning("claude_respond tentative %d échouée: %s", attempt + 1, exc)
                continue
            break
        except httpx.HTTPStatusError as exc:
            logger.error("claude_respond HTTP %s: %s", exc.response.status_code, exc.response.text)
            raise

    raise RuntimeError(f"claude_respond: échec après {HTTP_MAX_RETRIES + 1} tentatives — {last_exc}")


async def claude_chat(
    messages: list[Message],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    effort: str | None = "low",
    timeout: float | None = None,
) -> tuple[str, str]:
    """Forme courte pour le débat et l'arbitrage : effort low par défaut → (content, model_used)."""
    result = await claude_respond(messages, model=model, max_tokens=max_tokens,
                                  effort=effort, timeout=timeout)
    return result.text, result.model
