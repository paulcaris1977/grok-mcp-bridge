"""
Grok MCP Bridge — main.py
"""

import os
import logging
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

mcp = FastMCP(name="grok-mcp-bridge")

register_dispatch(mcp)
register_critique(mcp)
register_code_test(mcp)
register_research(mcp)
logger.info("All tools registered.")

if __name__ == "__main__":
    logger.info("Starting mcp.run()...")
    mcp.run()
