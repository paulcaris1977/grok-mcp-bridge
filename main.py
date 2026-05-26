"""
Grok MCP Bridge — main.py
Point d'entrée du serveur FastMCP v2.0
"""

import os
import logging
from fastmcp import FastMCP
from fastapi import FastAPI, Response

# Import des tools
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
mcp = FastMCP(
    name="grok-mcp-bridge",
    version="2.0.0",
    description="Production MCP Bridge — Claude ↔ Grok xAI (Taranis Cooperage)",
)

# ── Enregistrement des tools ──────────────────────────────────────────────────
register_dispatch(mcp)
register_critique(mcp)
register_code_test(mcp)
register_research(mcp)
logger.info("All tools registered successfully: grok_dispatch, grok_critique, grok_code_test, grok_research")

# ── Ajout d'un endpoint /health (sécurisé) ───────────────────────────────────
# On récupère l'application FastAPI sous-jacente de manière compatible
app: FastAPI = mcp.app if hasattr(mcp, "app") else mcp.http_app()

@app.get("/health", tags=["monitoring"])
async def health_check():
    """Endpoint de santé pour Railway et monitoring."""
    return {
        "status": "healthy",
        "service": "grok-mcp-bridge",
        "version": "2.0.0",
        "models": {
            "fast": os.getenv("GROK_FAST_MODEL", "grok-3-mini"),
            "smart": os.getenv("GROK_SMART_MODEL", "grok-3"),
        },
        "context": "Taranis Cooperage (tonnellerie)",
    }

# ── Lancement du serveur ─────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    logger.info(f"Starting Grok MCP Bridge v2.0 on {host}:{port} [{transport}]")
    logger.info("Endpoint /health available for monitoring")

    mcp.run(transport=transport, host=host, port=port)
