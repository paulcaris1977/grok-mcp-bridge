"""
Grok MCP Bridge — main.py
Compatible FastMCP 2.x + StarletteWithLifespan
Health endpoint via pure ASGI wrapper (lifespan préservé).
"""

import os
import json
import logging
import uvicorn
from fastmcp import FastMCP

from tools.grok_dispatch import register_dispatch
from tools.grok_critique import register_critique
from tools.grok_code_test import register_code_test
from tools.grok_research import register_research

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("grok-mcp-bridge")

# ── Initialisation FastMCP ────────────────────────────────────────────────────
mcp = FastMCP(name="grok-mcp-bridge")

# ── Enregistrement des tools ──────────────────────────────────────────────────
register_dispatch(mcp)
register_critique(mcp)
register_code_test(mcp)
register_research(mcp)
logger.info("All tools registered: grok_dispatch, grok_critique, grok_code_test, grok_research")

# ── ASGI wrapper pour /health ─────────────────────────────────────────────────
# Approche pure ASGI — fonctionne avec StarletteWithLifespan sans toucher aux internals.
# Le lifespan (startup/shutdown FastMCP) est préservé : tout scope non-HTTP
# (type="lifespan", type="websocket") passe directement à mcp.app.

_HEALTH_BODY = json.dumps({
    "status": "healthy",
    "service": "grok-mcp-bridge",
    "version": "2.0.0",
    "models": {
        "fast":  os.getenv("GROK_FAST_MODEL",  "grok-3-mini"),
        "smart": os.getenv("GROK_SMART_MODEL", "grok-3"),
    },
    "context": "Taranis Cooperage Group",
}, ensure_ascii=False).encode()

_HEALTH_HEADERS = [
    (b"content-type",   b"application/json"),
    (b"content-length", str(len(_HEALTH_BODY)).encode()),
]


async def asgi_app(scope, receive, send):
    """
    Wrapper ASGI :
    - GET /health  → réponse JSON directe (pas de dépendance FastAPI/Starlette)
    - tout le reste → délégué à mcp.app (MCP + lifespan + websocket)
    """
    if scope.get("type") == "http" and scope.get("path") == "/health":
        await send({"type": "http.response.start", "status": 200, "headers": _HEALTH_HEADERS})
        await send({"type": "http.response.body", "body": _HEALTH_BODY})
    else:
        await mcp.app(scope, receive, send)


# ── Lancement ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")

    logger.info(f"Starting Grok MCP Bridge v2.0 on {host}:{port}")
    logger.info("Endpoints : /mcp (bridge) + /health (monitoring)")

    uvicorn.run(asgi_app, host=host, port=port)
