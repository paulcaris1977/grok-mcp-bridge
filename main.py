"""
Grok MCP Bridge — main.py
FastMCP 2.14.x — transport streamable-http
"""

import os
import logging
from fastmcp import FastMCP

from tools.grok_dispatch import register_dispatch
from tools.grok_critique import register_critique
from tools.grok_code_test import register_code_test
from tools.grok_research import register_research
from tools.grok_debate import register_debate
from tools.ask_claude import register_ask_claude
from tools.project_memory import register_project_memory
from config import validate_api_keys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("grok-mcp-bridge")

mcp = FastMCP(name="grok-mcp-bridge")

validate_api_keys()
logger.info("API keys validated")

register_dispatch(mcp)
register_critique(mcp)
register_code_test(mcp)
register_research(mcp)
register_debate(mcp)
register_ask_claude(mcp)
register_project_memory(mcp)

logger.info(
    "All tools registered (dispatch, critique, code_test, research, debate, ask_claude, project_memory)."
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Starting on {host}:{port} [streamable-http]")
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
    )
