"""
grok_client.py
Client centralisé pour Grok (xAI) avec retry, quota management et historique.
"""

import os
import time
import logging
import asyncio
from typing import Optional, Dict, Any
from openai import AsyncOpenAI, RateLimitError, APIStatusError, APIConnectionError

logger = logging.getLogger("grok-mcp-bridge.client")

# ── Configuration ─────────────────────────────────────────────────────────────
GROK_API_KEY = os.environ.get("XAI_API_KEY", "")
GROK_BASE_URL = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")

DEFAULT_MODEL = os.environ.get("GROK_MODEL", "grok-3-mini")
FAST_MODEL = os.environ.get("GROK_FAST_MODEL", "grok-3-mini")
SMART_MODEL = os.environ.get("GROK_SMART_MODEL", "grok-3")

MAX_TOKENS = int(os.environ.get("GROK_MAX_TOKENS", "8192"))
MAX_RETRIES = int(os.environ.get("GROK_MAX_RETRIES", "4"))
RETRY_BASE_S = float(os.environ.get("GROK_RETRY_BASE_S", "1.8"))
CALL_TIMEOUT_S = float(os.environ.get("GROK_CALL_TIMEOUT_S", "25.0"))

# Historique par session
_history: Dict[str, list[dict]] = {}


def _get_client() -> AsyncOpenAI:
    if not GROK_API_KEY:
        raise ValueError("XAI_API_KEY is not set in environment variables.")
    return AsyncOpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL)


async def call_grok(
    prompt: str,
    system_prompt: str = "",
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    session_id: Optional[str] = None,
    use_history: bool = False,
) -> str:
    """
    Appel principal à Grok avec retry exponentiel et robustesse.
    """
    selected_model = model or DEFAULT_MODEL
    client = _get_client()
    max_tokens = max_tokens or MAX_TOKENS

    # Construction des messages
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    if use_history and session_id and session_id in _history:
        messages.extend(_history[session_id])

    messages.append({"role": "user", "content": prompt})

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"[{selected_model}] attempt={attempt}/{MAX_RETRIES} | "
                       f"model={selected_model} | tokens={max_tokens}")

            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=selected_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ),
                timeout=CALL_TIMEOUT_S,
            )
            content = response.choices[0].message.content or ""

            # Mise à jour historique (seulement en cas de succès)
            if use_history and session_id:
                if session_id not in _history:
                    _history[session_id] = []
                _history[session_id].append({"role": "user", "content": prompt})
                _history[session_id].append({"role": "assistant", "content": content})

                # Limite intelligente
                if len(_history[session_id]) > 30:
                    _history[session_id] = _history[session_id][-30:]

            logger.info(f"[{selected_model}] ✓ Success — {len(content)} chars")
            return content

        except RateLimitError as e:
            wait = RETRY_BASE_S * (2 ** (attempt - 1))
            logger.warning(f"Rate limit → waiting {wait:.1f}s (attempt {attempt})")
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Grok rate limit exceeded after {MAX_RETRIES} retries") from e
            await asyncio.sleep(wait)

        except asyncio.TimeoutError:
            logger.warning(f"Grok timeout after {CALL_TIMEOUT_S}s (attempt {attempt}/{MAX_RETRIES})")
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"Grok API timeout after {CALL_TIMEOUT_S}s — no response received")
            await asyncio.sleep(1.5)

        except (APIStatusError, APIConnectionError) as e:
            logger.error(f"Grok API error [{getattr(e, 'status_code', 'N/A')}]: {e}")
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(1.5)

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            if attempt == MAX_RETRIES:
                raise
            await asyncio.sleep(2)

    raise RuntimeError("Failed to get response from Grok after all retries")


def clear_history(session_id: str) -> None:
    """Vide l'historique d'une session."""
    _history.pop(session_id, None)
    logger.info(f"History cleared for session={session_id}")


def get_model_for_task(task_type: str) -> str:
    """Retourne le meilleur modèle selon le type de tâche."""
    mapping = {
        "fast": FAST_MODEL,
        "dispatch": FAST_MODEL,
        "critique": SMART_MODEL,
        "code": SMART_MODEL,
        "research": SMART_MODEL,
        "x_analysis": SMART_MODEL,
        "raw": SMART_MODEL,
    }
    return mapping.get(task_type, DEFAULT_MODEL)
