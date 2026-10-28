"""
grok_client.py
Client unique pour Grok (xAI), via la Responses API (POST /v1/responses).

- Profils d'effort (config.EFFORT_PROFILES) : modèle, reasoning.effort, budget,
  tours d'outils, timeout.
- Outils serveur xAI (web_search, x_search) : la recherche est faite par xAI,
  les citations reviennent dans la réponse.
- Chaque réponse peut se terminer par une ligne de coût estimé.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from config import (
    XAI_API_KEY, GROK_BASE_URL,
    EFFORT_PROFILES, DEFAULT_EFFORT, EFFORT_CAPABLE_MODELS, REASONING_MODELS,
    GROK_PRICES, GROK_TOOL_CALL_PRICE,
)

logger = logging.getLogger("grok-mcp-bridge.client")

MAX_RETRIES = int(os.environ.get("GROK_MAX_RETRIES", "1"))   # 1 retry = 2 tentatives max

# Historique par session (mémoire du process, perdu au redéploiement — phase 3)
_history: dict[str, list[dict]] = {}
_HISTORY_KEEP = 30

Message = dict[str, Any]


@dataclass
class GrokResult:
    text: str
    model: str
    effort: str
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    tool_calls: dict[str, int] = field(default_factory=dict)
    citations: list[str] = field(default_factory=list)

    @property
    def cost_usd(self) -> Optional[float]:
        price = GROK_PRICES.get(self.model)
        if not price:
            return None
        tokens = (self.input_tokens * price[0] + self.output_tokens * price[1]) / 1_000_000
        return tokens + sum(self.tool_calls.values()) * GROK_TOOL_CALL_PRICE

    def footer(self) -> str:
        parts = [self.model, f"effort {self.effort}",
                 f"{self.input_tokens:,} → {self.output_tokens:,} tokens".replace(",", " ")]
        if self.reasoning_tokens:
            parts[-1] += f" (dont {self.reasoning_tokens:,} de raisonnement)".replace(",", " ")
        for name, count in self.tool_calls.items():
            parts.append(f"{name} ×{count}")
        cost = self.cost_usd
        parts.append(f"≈ {cost:.3f} $" if cost is not None else "coût inconnu")
        return "`" + " · ".join(parts) + "`"

    def render(self, footer: bool = True) -> str:
        out = self.text
        if self.citations:
            out += "\n\n**Sources**\n" + "\n".join(
                f"{i}. {url}" for i, url in enumerate(self.citations, 1))
        if footer:
            out += "\n\n---\n" + self.footer()
        return out


def resolve_effort(effort: Optional[str]) -> str:
    effort = (effort or DEFAULT_EFFORT).strip().lower()
    if effort not in EFFORT_PROFILES:
        raise ValueError(f"effort inconnu '{effort}' (valeurs : {', '.join(EFFORT_PROFILES)})")
    return effort


def search_tools(sources: str = "web+x") -> list[dict]:
    """Outils serveur xAI pour une recherche. sources : 'web', 'x' ou 'web+x'."""
    wanted = {s.strip() for s in sources.lower().split("+")}
    tools = []
    if "web" in wanted:
        tools.append({"type": "web_search"})
    if "x" in wanted:
        tools.append({"type": "x_search"})
    if not tools:
        raise ValueError(f"sources inconnues '{sources}' (valeurs : web, x, web+x)")
    return tools


def build_payload(
    messages: list[Message],
    effort: str,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    tools: Optional[list[dict]] = None,
) -> dict[str, Any]:
    profile = EFFORT_PROFILES[effort]
    selected = model or profile["model"]
    payload: dict[str, Any] = {
        "model": selected,
        "input": messages,
        "max_output_tokens": max_output_tokens or profile["max_output_tokens"],
    }
    if profile["reasoning"] and selected in EFFORT_CAPABLE_MODELS:
        payload["reasoning"] = {"effort": profile["reasoning"]}
    if temperature is not None and selected not in REASONING_MODELS:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = tools
        payload["max_turns"] = profile["max_turns"]
    return payload


def parse_response(data: dict[str, Any], effort: str, requested_model: str) -> GrokResult:
    texts: list[str] = []
    citations: list[str] = []
    tool_calls: dict[str, int] = {}

    for item in data.get("output", []) or []:
        kind = item.get("type", "")
        if kind == "message":
            for block in item.get("content", []) or []:
                if block.get("type") == "output_text":
                    texts.append(block.get("text", ""))
                    for ann in block.get("annotations", []) or []:
                        url = ann.get("url")
                        if ann.get("type") == "url_citation" and url and url not in citations:
                            citations.append(url)
        elif kind.endswith("_call"):
            name = kind[: -len("_call")]
            tool_calls[name] = tool_calls.get(name, 0) + 1

    for url in data.get("citations", []) or []:
        if isinstance(url, str) and url not in citations:
            citations.append(url)

    usage = data.get("usage", {}) or {}
    details = usage.get("output_tokens_details", {}) or {}
    text = "\n\n".join(t for t in texts if t).strip()
    if not text:
        raise RuntimeError(
            f"Grok: réponse sans texte (status={data.get('status')}, "
            f"incomplete={data.get('incomplete_details')})")

    return GrokResult(
        text=text,
        model=data.get("model", requested_model),
        effort=effort,
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        reasoning_tokens=int(details.get("reasoning_tokens", 0) or 0),
        tool_calls=tool_calls,
        citations=citations,
    )


async def grok_respond(
    messages: list[Message],
    *,
    effort: Optional[str] = None,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    tools: Optional[list[dict]] = None,
    timeout_s: Optional[float] = None,
) -> GrokResult:
    """Appel bas niveau : messages → GrokResult. Relance sur 429 / 5xx / réseau."""
    if not XAI_API_KEY:
        raise ValueError("XAI_API_KEY is not set in environment variables.")
    effort = resolve_effort(effort)
    payload = build_payload(messages, effort, model, temperature, max_output_tokens, tools)
    budget = timeout_s or EFFORT_PROFILES[effort]["timeout_s"]
    deadline = time.monotonic() + budget
    headers = {"Authorization": f"Bearer {XAI_API_KEY}", "Content-Type": "application/json"}

    last_exc: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            break
        logger.info("[%s] effort=%s attempt=%d tools=%s budget=%.0fs",
                    payload["model"], effort, attempt,
                    [t["type"] for t in tools or []], remaining)
        try:
            async with httpx.AsyncClient(timeout=remaining) as client:
                resp = await client.post(f"{GROK_BASE_URL}/responses", json=payload, headers=headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = RuntimeError(f"Grok HTTP {resp.status_code}: {resp.text[:300]}")
                logger.warning("%s", last_exc)
                await asyncio.sleep(min(2.0 * attempt, max(deadline - time.monotonic() - 1, 0)))
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"Grok HTTP {resp.status_code}: {resp.text[:500]}")
            result = parse_response(resp.json(), effort, payload["model"])
            logger.info("[%s] ✓ %s", result.model, result.footer())
            return result
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            last_exc = exc
            logger.warning("Grok réseau/timeout (attempt %d): %s", attempt, exc)

    raise RuntimeError(f"Grok: échec dans le budget de {budget:.0f}s — {last_exc}")


async def call_grok(
    prompt: str,
    system_prompt: str = "",
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    session_id: Optional[str] = None,
    use_history: bool = False,
    effort: Optional[str] = None,
    tools: Optional[list[dict]] = None,
    footer: bool = True,
) -> str:
    """Appel haut niveau utilisé par les tools : prompt → texte + sources + ligne de coût."""
    messages: list[Message] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if use_history and session_id and session_id in _history:
        messages.extend(_history[session_id])
    messages.append({"role": "user", "content": prompt})

    result = await grok_respond(
        messages, effort=effort, model=model, temperature=temperature,
        max_output_tokens=max_tokens, tools=tools)

    if use_history and session_id:
        hist = _history.setdefault(session_id, [])
        hist.append({"role": "user", "content": prompt})
        hist.append({"role": "assistant", "content": result.text})
        _history[session_id] = hist[-_HISTORY_KEEP:]

    return result.render(footer=footer)


def clear_history(session_id: str) -> None:
    """Vide l'historique d'une session."""
    _history.pop(session_id, None)
    logger.info(f"History cleared for session={session_id}")
