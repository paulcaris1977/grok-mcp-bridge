"""
utils/json_parser.py
Extraction robuste et multi-stratégies de JSON depuis les réponses Grok.
Grok étant parfois verbeux, ce parser est critique pour la fiabilité du bridge.
"""

import re
import json
import logging
from typing import Any, Optional

logger = logging.getLogger("grok-mcp-bridge.json_parser")

def extract_json(raw: str, expect_type: type = dict) -> Optional[Any]:
    """
    Extraction robuste de JSON.
    Stratégies dans l'ordre de préférence :
    1. Parse direct
    2. Blocs markdown (json ou generique)
    3. Detection intelligente du plus grand objet JSON valide
    4. Nettoyage agressif + retry
    """
    if not raw or not raw.strip():
        logger.warning("extract_json: received empty string")
        return None

    text = raw.strip()

    # Strategie 1 : Parse direct
    try:
        result = json.loads(text)
        if isinstance(result, expect_type):
            return result
    except json.JSONDecodeError:
        pass

    # Strategie 2 : Blocs markdown
    for pattern in [
        r"```(?:json)?\s*\n?([\s\S]+?)\n?```",
        r"```\s*([\s\S]+?)\n?```",
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
            try:
                result = json.loads(candidate)
                if isinstance(result, expect_type):
                    logger.debug("JSON extracted from markdown code block")
                    return result
            except json.JSONDecodeError:
                cleaned = _clean_json_string(candidate)
                try:
                    result = json.loads(cleaned)
                    if isinstance(result, expect_type):
                        logger.debug("JSON extracted after cleaning markdown block")
                        return result
                except json.JSONDecodeError:
                    continue

    # Strategie 3 : Detection intelligente du plus grand objet JSON valide
    if expect_type == dict:
        matches = re.findall(r'(\{[\s\S]*?\})', text)
        for m in sorted(matches, key=len, reverse=True):
            cleaned = _clean_json_string(m)
            try:
                result = json.loads(cleaned)
                if isinstance(result, dict):
                    logger.debug("JSON extracted via smart brace matching")
                    return result
            except json.JSONDecodeError:
                continue

    elif expect_type == list:
        matches = re.findall(r'(\[[\s\S]*?\])', text)
        for m in sorted(matches, key=len, reverse=True):
            cleaned = _clean_json_string(m)
            try:
                result = json.loads(cleaned)
                if isinstance(result, list):
                    return result
            except json.JSONDecodeError:
                continue

    logger.warning(f"Failed to extract {expect_type.__name__} from Grok response ({len(text)} chars)")
    return None


def safe_parse(raw: str, fallback: Any = None) -> Any:
    """Version sure avec fallback."""
    result = extract_json(raw)
    if result is None:
        result = extract_json(raw, expect_type=list)
    return result if result is not None else fallback


def _clean_json_string(text: str) -> str:
    """
    Nettoyage agressif pour JSON mal forme.
    Ordre critique : strip texte parasite -> strip commentaires -> trailing commas.
    """
    text = text.strip()

    # 1. Supprime texte avant/apres le JSON (ex: "Voici le JSON: {..} fin")
    text = re.sub(r'^.*?(\{|\[)', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'(\}|\]).*?$', r'\1', text, flags=re.DOTALL)

    # 2. Supprime commentaires // et /* */ (peut creer des trailing commas)
    text = re.sub(r'//.*?$', '', text, flags=re.MULTILINE)
    text = re.sub(r'/\*[\s\S]*?\*/', '', text)

    # 3. Trailing commas EN DERNIER (apres le strip des commentaires)
    text = re.sub(r',\s*([\}\]])', r'\1', text)

    return text.strip()


def format_as_json_str(data: Any, indent: int = 2) -> str:
    """Utilitaire pour renvoyer du JSON propre."""
    return json.dumps(data, ensure_ascii=False, indent=indent)
