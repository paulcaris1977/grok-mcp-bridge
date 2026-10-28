"""
Tests phase 1 : profils d'effort, payload Responses API, parsing (texte,
citations, outils, coût), relances HTTP, transmission effort/model par dispatch.
Aucun appel réseau : httpx passe par un MockTransport.
"""

import httpx
import pytest

import grok_client
import tools.grok_research as research_mod
from grok_client import build_payload, parse_response, resolve_effort, search_tools

SAMPLE = {
    "model": "grok-4.7",
    "status": "completed",
    "output": [
        {"type": "reasoning", "summary": []},
        {"type": "web_search_call", "status": "completed"},
        {"type": "web_search_call", "status": "completed"},
        {"type": "x_search_call", "status": "completed"},
        {
            "type": "message",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": "Demande soutenue [[1]](https://a.example) [[2]](https://b.example) [[1]](https://a.example)",
                "annotations": [
                    {"type": "url_citation", "url": "https://a.example", "title": "1"},
                    {"type": "url_citation", "url": "https://b.example", "title": "2"},
                    {"type": "url_citation", "url": "https://a.example", "title": "1"},
                ],
            }],
        },
    ],
    "usage": {"input_tokens": 1000, "output_tokens": 2000,
              "output_tokens_details": {"reasoning_tokens": 1500}},
}


def test_low_profile_has_no_reasoning_and_keeps_temperature():
    p = build_payload([{"role": "user", "content": "x"}], "low", temperature=0.3)
    assert p["model"] == "grok-4.20-0309-non-reasoning"
    assert "reasoning" not in p
    assert p["temperature"] == 0.3
    assert "tools" not in p and "max_turns" not in p


def test_high_profile_uses_reasoning_effort_without_temperature():
    p = build_payload([{"role": "user", "content": "x"}], "high", temperature=0.7,
                      tools=search_tools("web"))
    assert p["model"] == "grok-4.7"
    assert p["reasoning"] == {"effort": "high"}
    assert "temperature" not in p
    assert p["tools"] == [{"type": "web_search"}]
    assert p["max_turns"] == 6


def test_forced_model_without_effort_support_drops_reasoning():
    p = build_payload([{"role": "user", "content": "x"}], "max", model="grok-4.3")
    assert p["model"] == "grok-4.3"
    assert "reasoning" not in p


def test_invalid_effort_and_sources_are_rejected():
    with pytest.raises(ValueError):
        resolve_effort("turbo")
    with pytest.raises(ValueError):
        search_tools("linkedin")
    assert resolve_effort(None) == "medium"


def test_parse_response_text_citations_tools_cost():
    r = parse_response(SAMPLE, "high", "grok-4.7")
    assert r.text.startswith("Demande soutenue")
    assert r.citations == ["https://a.example", "https://b.example"]
    assert r.tool_calls == {"web_search": 2, "x_search": 1}
    assert r.reasoning_tokens == 1500
    # 1000 × 2 $/M + 2000 × 6 $/M + 3 outils × 0,005 $ = 0,002 + 0,012 + 0,015
    assert r.cost_usd == pytest.approx(0.029)
    out = r.render()
    assert "**Sources**\n1. https://a.example\n2. https://b.example" in out
    assert "web_search ×2" in out and "≈ 0.029 $" in out


def test_parse_response_without_text_raises():
    with pytest.raises(RuntimeError):
        parse_response({"status": "incomplete", "output": []}, "low", "m")


def _mock_client(monkeypatch, responses, seen):
    real = httpx.AsyncClient

    def handler(request):
        seen.append(request)
        return responses.pop(0)

    monkeypatch.setattr(grok_client.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(grok_client, "XAI_API_KEY", "test")
    monkeypatch.setattr(grok_client.asyncio, "sleep", _no_sleep)


async def _no_sleep(_):
    return None


@pytest.mark.asyncio
async def test_retry_on_503_then_success(monkeypatch):
    seen = []
    _mock_client(monkeypatch, [httpx.Response(503, text="busy"), httpx.Response(200, json=SAMPLE)], seen)
    r = await grok_client.grok_respond([{"role": "user", "content": "x"}], effort="high")
    assert r.model == "grok-4.7" and len(seen) == 2
    assert seen[0].url.path == "/v1/responses"


@pytest.mark.asyncio
async def test_400_is_not_retried(monkeypatch):
    seen = []
    _mock_client(monkeypatch, [httpx.Response(400, text="bad param")], seen)
    with pytest.raises(RuntimeError, match="400"):
        await grok_client.grok_respond([{"role": "user", "content": "x"}], effort="low")
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_dispatch_forwards_effort_and_model(monkeypatch):
    calls = []

    async def _fake(**kwargs):
        calls.append(kwargs)
        return "OK"

    monkeypatch.setattr(research_mod, "call_grok", _fake)
    mcp_text = await _dispatch_with("Veille marché Corée", "research", effort="low", model="grok-4.6")
    assert mcp_text == "OK"
    assert calls[0]["effort"] == "low" and calls[0]["model"] == "grok-4.6"


@pytest.mark.asyncio
async def test_research_depth_maps_to_effort(monkeypatch):
    calls = []

    async def _fake(**kwargs):
        calls.append(kwargs)
        return "OK"

    monkeypatch.setattr(research_mod, "call_grok", _fake)
    await research_mod._run_research("x", depth="deep")
    await research_mod._run_research("x", depth="deep", effort="max")
    assert [c["effort"] for c in calls] == ["high", "max"]


async def _dispatch_with(prompt, task, **extra):
    from fastmcp import Client, FastMCP
    from tools.grok_dispatch import register_dispatch
    mcp = FastMCP(name="test")
    register_dispatch(mcp)
    async with Client(mcp) as client:
        result = await client.call_tool("grok_dispatch", {"prompt": prompt, "task": task, **extra})
    return result.content[0].text
