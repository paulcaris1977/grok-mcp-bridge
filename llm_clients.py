"""
llm_clients.py — Grok-Claude Bridge
Clients du mode debate bi-directionnel.
Grok passe par grok_client (client unique, Responses API) ; Claude par httpx direct.

Deux fonctions publiques :
  - grok_chat(messages, **kwargs)   → (content: str, model: str)
  - claude_chat(messages, **kwargs) → (content: str, model: str)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from grok_client import grok_respond
from config import (
    ANTHROPIC_API_KEY, CLAUDE_BASE_URL, CLAUDE_MODEL,
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


async def claude_chat(
    messages: list[Message],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.7,
    timeout: float | None = None,
) -> tuple[str, str]:
    """
    Appel Claude via Anthropic Messages API.
    Gère la conversion system + alternance user/assistant.
    Retourne (content, model_used).
    """
    _model      = model      or CLAUDE_MODEL
    _max_tokens = max_tokens or DEBATE_MAX_TOKENS

    system_prompt, filtered = _extract_system(messages)

    # Anthropic exige que le 1er message soit "user"
    if not filtered or filtered[0]["role"] != "user":
        filtered.insert(0, {"role": "user", "content": "Commence."})

    # Anthropic exige une alternance stricte user/assistant
    # Si deux messages consécutifs ont le même role, on fusionne
    merged: list[Message] = []
    for msg in filtered:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"] += "\n\n" + msg["content"]
        else:
            merged.append({"role": msg["role"], "content": msg["content"]})

    payload: dict[str, Any] = {
        "model":       _model,
        "max_tokens":  _max_tokens,
        "temperature": temperature,
        "messages":    merged,
    }
    if system_prompt:
        payload["system"] = system_prompt

    headers = {
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type":      "application/json",
    }

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

            blocks = data.get("content", [])
            if not blocks:
                raise ValueError("Claude: réponse sans 'content' (vérifiez le modèle et la clé API)")

            content    = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            model_used = data.get("model", _model)
            logger.debug("claude_chat [%s] → %d chars", model_used, len(content))
            return content, model_used

        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            if attempt < HTTP_MAX_RETRIES:
                logger.warning("claude_chat tentative %d échouée: %s", attempt + 1, exc)
                continue
            break
        except httpx.HTTPStatusError as exc:
            logger.error("claude_chat HTTP %s: %s", exc.response.status_code, exc.response.text)
            raise

    raise RuntimeError(f"claude_chat: échec après {HTTP_MAX_RETRIES + 1} tentatives — {last_exc}")
