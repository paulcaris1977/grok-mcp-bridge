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
from tools.grok_orchestration import register_orchestration
from tools.grok_x_pulse import register_x_pulse
from tools.grok_structured import register_structured
from tools.grok_jobs import register_jobs
from tools.grok_workflow import register_workflow
from tools.grok_vision import register_vision
import store
from config import validate_api_keys
from auth import protect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("grok-mcp-bridge")

mcp = FastMCP(name="grok-mcp-bridge")

validate_api_keys()
logger.info("API keys validated")

store.init()

register_dispatch(mcp)
register_critique(mcp)
register_code_test(mcp)
register_research(mcp)
register_debate(mcp)
register_ask_claude(mcp)
register_project_memory(mcp)
register_orchestration(mcp)
register_x_pulse(mcp)
register_structured(mcp)
register_jobs(mcp)
register_workflow(mcp)
register_vision(mcp)

logger.info(
    "All tools registered (dispatch, critique, code_test, research, debate, ask_claude, project_memory, "
    "verify, cross_check, x_pulse, structured, jobs, workflow, vision)."
)

# App ASGI exposée au niveau module : Railway démarre via `uvicorn main:app`
app = protect(mcp.http_app(path="/mcp", transport="streamable-http"))

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Starting on {host}:{port} [streamable-http]")
    uvicorn.run(app, host=host, port=port)
