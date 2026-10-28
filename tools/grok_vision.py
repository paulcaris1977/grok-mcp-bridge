"""
tools/grok_vision.py
Analyse d'images par Grok : photos de fûts ou de défauts, étiquettes, fiches
techniques, captures de tableaux. Images en URL publique ou en data URI base64 (JPEG/PNG).
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Union

from fastmcp import FastMCP

from config import GROK_VISION_MODEL
from context import build_system_prompt
from grok_client import grok_respond

logger = logging.getLogger("grok-mcp-bridge.vision")

MAX_IMAGES = 10
_DATA_URI_RE = re.compile(r"^data:image/(jpeg|jpg|png);base64,[A-Za-z0-9+/=\s]+$")

_VISION_EXTRA = """
Tu analyses une ou plusieurs images pour Taranis. Décris uniquement ce qui est visible.
Si un détail est illisible ou incertain (marquage, chiffre, défaut), dis-le au lieu de deviner.
""".strip()


def image_blocks(images: Union[list[str], str], detail: str = "high") -> list[dict]:
    if isinstance(images, str):
        images = [images]
    images = [i.strip() for i in images if i and i.strip()]
    if not images:
        raise ValueError("au moins une image (URL https ou data URI base64)")
    if len(images) > MAX_IMAGES:
        raise ValueError(f"{len(images)} images : maximum {MAX_IMAGES}")
    if detail not in ("low", "high", "auto"):
        raise ValueError("detail = low | high | auto")
    blocks = []
    for n, img in enumerate(images, 1):
        if not (img.startswith(("https://", "http://")) or _DATA_URI_RE.match(img)):
            raise ValueError(f"image {n} : URL http(s) ou data:image/jpeg|png;base64,… attendue")
        blocks.append({"type": "input_image", "image_url": img, "detail": detail})
    return blocks


def register_vision(mcp: FastMCP) -> None:

    @mcp.tool(
        name="grok_vision",
        description=(
            "Grok analyse des images : état d'un fût, défaut, marquage, étiquette, fiche technique, "
            "capture de tableau. images = liste d'URL publiques ou de data URI base64 (JPEG/PNG, 20 Mo max, "
            f"{MAX_IMAGES} max). detail = high | low | auto. effort = low | medium | high | max."
        ),
    )
    async def grok_vision(
        prompt: str,
        images: Union[list[str], str],
        effort: str = "medium",
        detail: str = "high",
        model: Optional[str] = None,
    ) -> str:
        try:
            blocks = image_blocks(images, detail)
        except ValueError as exc:
            return f"❌ grok_vision : {exc}"
        logger.info("grok_vision | images=%d | effort=%s | model=%s", len(blocks), effort,
                    model or GROK_VISION_MODEL)
        try:
            result = await grok_respond(
                [{"role": "system", "content": build_system_prompt(task_type="dispatch",
                                                                   extra_instructions=_VISION_EXTRA)},
                 {"role": "user", "content": [{"type": "input_text", "text": prompt}, *blocks]}],
                effort=effort, model=model or GROK_VISION_MODEL, store=False)
        except Exception as exc:
            logger.error("grok_vision: %s", exc, exc_info=True)
            return f"❌ Erreur grok_vision ({type(exc).__name__}) : {exc}"
        return result.render()
