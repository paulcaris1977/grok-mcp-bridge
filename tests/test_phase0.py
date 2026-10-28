"""
Tests phase 0 : routage dispatch → handlers, outils de recherche,
contexte Taranis chargé depuis fichier, garde Bearer.
Aucun appel réseau : call_grok est remplacé par un faux.
"""

import httpx
import pytest
from fastmcp import Client, FastMCP

import context.taranis_context as ctx
import tools.grok_critique as critique_mod
import tools.grok_research as research_mod
from auth import protect
from tools.grok_dispatch import register_dispatch


@pytest.fixture
def fake_grok(monkeypatch):
    calls = []

    async def _fake(**kwargs):
        calls.append(kwargs)
        return "OK"

    monkeypatch.setattr(critique_mod, "call_grok", _fake)
    monkeypatch.setattr(research_mod, "call_grok", _fake)
    return calls


async def _dispatch(prompt, task):
    mcp = FastMCP(name="test")
    register_dispatch(mcp)
    async with Client(mcp) as client:
        result = await client.call_tool("grok_dispatch", {"prompt": prompt, "task": task})
    return result.content[0].text


@pytest.mark.asyncio
async def test_dispatch_critique_reaches_handler(fake_grok):
    text = await _dispatch("Critique ce plan Japon", "critique")
    assert text == "OK"
    assert "Critique ce plan Japon" in fake_grok[0]["prompt"]


@pytest.mark.asyncio
async def test_dispatch_research_reaches_handler_with_search_tools(fake_grok):
    text = await _dispatch("Prix des fûts bourbon en Écosse", "research")
    assert text == "OK"
    assert "Prix des fûts bourbon en Écosse" in fake_grok[0]["prompt"]
    assert [t["type"] for t in fake_grok[0]["tools"]] == ["web_search", "x_search"]


@pytest.mark.asyncio
async def test_dispatch_error_does_not_call_grok_again(monkeypatch):
    calls = []

    async def _boom(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("panne xAI")

    # research laisse remonter l'exception (critique la capture elle-même)
    monkeypatch.setattr(research_mod, "call_grok", _boom)
    text = await _dispatch("Prix des fûts en Corée", "research")
    assert text.startswith("❌ Erreur grok_dispatch")
    assert len(calls) == 1


def test_base_context_is_current():
    assert "Querceo ne vend JAMAIS de fûts" in ctx._BASE_CONTEXT
    assert "Géorgie" in ctx._BASE_CONTEXT


def test_context_override(monkeypatch, tmp_path):
    custom = tmp_path / "ctx.md"
    custom.write_text("Contexte de test", encoding="utf-8")
    monkeypatch.setenv("TARANIS_CONTEXT_PATH", str(custom))
    assert ctx._load_base_context() == "Contexte de test"
    monkeypatch.setenv("TARANIS_CONTEXT_PATH", str(tmp_path / "absent.md"))
    assert "Taranis Cooperage Group" in ctx._load_base_context()


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


@pytest.mark.asyncio
async def test_bearer_auth(monkeypatch):
    monkeypatch.setenv("MCP_BEARER_TOKEN", "s3cret")
    transport = httpx.ASGITransport(app=protect(_ok_app))
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.post("/mcp")).status_code == 401
        assert (await c.post("/mcp", headers={"Authorization": "Bearer faux"})).status_code == 401
        assert (await c.post("/mcp", headers={"Authorization": "Bearer s3cret"})).status_code == 200
        assert (await c.options("/mcp")).status_code == 200


def test_no_token_leaves_app_open(monkeypatch):
    monkeypatch.delenv("MCP_BEARER_TOKEN", raising=False)
    assert protect(_ok_app) is _ok_app
