"""
Tests phase 3 : stockage SQLite, tâches de fond, workflow générique, vision.
Aucun appel réseau.
"""

import asyncio
import json

import pytest
from fastmcp import Client, FastMCP

import grok_client
import jobs
import store
import workflow as wf_mod
import tools.grok_vision as vision_mod
from grok_client import GrokResult, build_payload
from llm_clients import ClaudeResult
from tools.grok_jobs import register_jobs
from tools.grok_vision import image_blocks, register_vision
from tools.project_memory import register_project_memory


def _grok(text="G"):
    return GrokResult(text=text, model="grok-4.7", effort="medium", input_tokens=1000, output_tokens=100)


async def _call(register, tool, args):
    mcp = FastMCP(name="test")
    register(mcp)
    async with Client(mcp) as client:
        res = await client.call_tool(tool, args)
    return res.content[0].text


# ── stockage ─────────────────────────────────────────────────────────────────

def test_legacy_json_notes_are_imported(tmp_path):
    legacy = tmp_path / "project_notes.json"
    legacy.write_text(json.dumps({"projects": {"nalmaia": {"notes": [
        {"key": "prix", "content": "réf.", "source": "grok", "updated_at": "2026-10-01T00:00:00+00:00"}]}}}),
        encoding="utf-8")
    store.init()
    assert store.list_notes("nalmaia")[0]["content"] == "réf."
    assert not legacy.exists() and (tmp_path / "project_notes.json.imported").exists()


@pytest.mark.asyncio
async def test_notes_tools_roundtrip():
    out = await _call(register_project_memory, "save_project_note",
                      {"project": "nalmaia", "key": "segments", "content": "premium"})
    assert "créée" in out
    out = await _call(register_project_memory, "save_project_note",
                      {"project": "nalmaia", "key": "segments", "content": "ultra"})
    assert "mise à jour" in out
    assert "ultra" in await _call(register_project_memory, "get_project_notes", {"project": "nalmaia"})
    assert "nalmaia" in await _call(register_project_memory, "get_project_notes", {})


@pytest.mark.asyncio
async def test_session_history_survives_in_sqlite(monkeypatch):
    seen = []

    async def fake(messages, **kw):
        seen.append(messages)
        return _grok("réponse")

    monkeypatch.setattr(grok_client, "grok_respond", fake)
    await grok_client.call_grok("q1", session_id="s1", use_history=True)
    await grok_client.call_grok("q2", session_id="s1", use_history=True)
    assert [m["content"] for m in seen[1]] == ["q1", "réponse", "q2"]
    grok_client.clear_history("s1")
    assert store.get_history("s1") == []


def test_store_flag_only_when_asked():
    msgs = [{"role": "user", "content": "x"}]
    assert "store" not in build_payload(msgs, "medium")
    assert build_payload(msgs, "medium", store=False)["store"] is False


# ── tâches de fond ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_job_runs_and_result_is_readable(monkeypatch):
    async def fake_research(**kw):
        await asyncio.sleep(0.05)
        return f"rapport {kw['query']}"

    monkeypatch.setitem(jobs.RUNNERS, "research", fake_research)
    job_id = await jobs.start("research", {"query": "fûts Inde"})
    job = await jobs.wait(job_id, 5)
    assert job["status"] == "done" and job["result"] == "rapport fûts Inde"


@pytest.mark.asyncio
async def test_job_failure_is_recorded(monkeypatch):
    async def boom(**kw):
        raise RuntimeError("xai down")

    monkeypatch.setitem(jobs.RUNNERS, "verify", boom)
    job = await jobs.wait(await jobs.start("verify", {"query": "x"}), 5)
    assert job["status"] == "failed" and "xai down" in job["error"]


@pytest.mark.asyncio
async def test_job_rejects_bad_kind_and_params():
    with pytest.raises(ValueError, match="kind inconnu"):
        await jobs.start("turbo", {})
    with pytest.raises(ValueError, match="params invalides"):
        await jobs.start("research", {"qeury": "typo"})
    with pytest.raises(ValueError, match="ne désigne aucune"):
        await jobs.start("workflow", {"steps": [{"id": "a", "prompt": "{{b}}"}]})


def test_restart_marks_running_jobs_interrupted():
    store.create_job("abc", "debate", {})
    store.update_job("abc", status="running")
    store.init()
    assert store.get_job("abc")["status"] == "interrupted"


@pytest.mark.asyncio
async def test_job_tools(monkeypatch):
    async def fake(**kw):
        return "fini"

    monkeypatch.setitem(jobs.RUNNERS, "cross_check", fake)
    mcp = FastMCP(name="test")
    register_jobs(mcp)
    async with Client(mcp) as client:
        out = (await client.call_tool("grok_start_job", {"kind": "cross_check",
                                                          "params": {"question": "Inde ?"}})).content[0].text
        job_id = out.split("`")[1]
        got = (await client.call_tool("grok_get_job", {"job_id": job_id, "wait_s": 5})).content[0].text
        listed = (await client.call_tool("grok_list_jobs", {})).content[0].text
        bad = (await client.call_tool("grok_start_job", {"kind": "turbo", "params": "{}"})).content[0].text
    assert "done" in got and "fini" in got and job_id in listed and "refusée" in bad


# ── workflow ──────────────────────────────────────────────────────────────────

def test_parse_steps_validation():
    groups = wf_mod.parse_steps('[{"id": "a", "prompt": "{{input}}"}, '
                                '[{"id": "b", "agent": "claude", "prompt": "{{a}}"}, {"id": "c", "prompt": "{{a}}"}]]')
    assert [[s.id for s in g] for g in groups] == [["a"], ["b", "c"]]
    for bad, msg in [
        ([{"id": "a", "prompt": "x"}, {"id": "a", "prompt": "y"}], "double"),
        ([[{"id": "a", "prompt": "x"}, {"id": "b", "prompt": "{{a}}"}]], "ne désigne aucune"),   # même groupe
        ([{"id": "a", "agent": "claude", "prompt": "x", "sources": "web"}], "réservé à Grok"),
        ([{"id": "a", "agent": "claude", "prompt": "x", "effort": "turbo"}], "effort Claude inconnu"),
        ([{"id": "a", "agent": "claude", "prompt": "x", "schema": {"x": 1}}], "champ 'type'"),
        ([{"id": "a", "prompt": "x", "effort": "turbo"}], "effort inconnu"),
        ([{"id": "a", "prompt": "x", "temp": 1}], "champs inconnus"),
        ([{"id": f"s{i}", "prompt": "x"} for i in range(9)], "maximum"),
    ]:
        with pytest.raises(ValueError, match=msg):
            wf_mod.parse_steps(bad)


@pytest.mark.asyncio
async def test_workflow_chains_outputs_and_runs_groups_in_parallel(monkeypatch):
    prompts = {}
    running, peak = 0, 0

    async def fake_grok(messages, **kw):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        prompts[messages[-1]["content"]] = kw
        return _grok(f"G[{messages[-1]['content']}]")

    async def fake_claude(messages, **kw):
        prompts[messages[-1]["content"]] = kw
        return ClaudeResult(f"C[{messages[-1]['content']}]", "claude-sonnet-5-5", kw["effort"], 1000, 100)

    monkeypatch.setattr(wf_mod, "grok_respond", fake_grok)
    monkeypatch.setattr(wf_mod, "claude_respond", fake_claude)
    progress = []
    res = await wf_mod.run_workflow(
        [[{"id": "a", "prompt": "A {{input}}", "sources": "web"}, {"id": "b", "prompt": "B"}],
         {"id": "c", "agent": "claude", "prompt": "{{a}} + {{b}}", "effort": "high",
          "schema": {"type": "object", "properties": {}, "additionalProperties": False}}],
        input="Inde", progress=progress.append)
    assert res.outputs[-1].text == "C[G[A Inde] + G[B]]"
    assert peak == 2 and prompts["A Inde"]["tools"] == [{"type": "web_search"}]
    assert prompts["G[A Inde] + G[B]"]["effort"] == "high" and prompts["G[A Inde] + G[B]"]["schema"]
    # Grok 2 × 0.0026 $ + Claude (1000 × 2 + 100 × 10) / 1M = 0.003 $
    assert abs(res.cost_usd - (2 * 0.0026 + 0.003)) < 1e-9 and progress[-1].startswith("terminé")
    assert "## Résultat (c, claude)" in wf_mod.format_workflow(res)


@pytest.mark.asyncio
async def test_workflow_stops_on_failed_step(monkeypatch):
    async def boom(messages, **kw):
        raise RuntimeError("xai down")

    monkeypatch.setattr(wf_mod, "grok_respond", boom)
    res = await wf_mod.run_workflow([{"id": "a", "prompt": "x"}, {"id": "b", "prompt": "{{a}}"}])
    assert "étape a" in res.error and not res.outputs


# ── vision ────────────────────────────────────────────────────────────────────

def test_image_blocks_validation():
    blocks = image_blocks(["https://x.example/fût.jpg", "data:image/png;base64,iVBORw0KGgo="])
    assert blocks[0] == {"type": "input_image", "image_url": "https://x.example/fût.jpg", "detail": "high"}
    for bad in ([], ["file:///c:/a.jpg"], ["data:image/gif;base64,AAA="], ["https://a"] * 11):
        with pytest.raises(ValueError):
            image_blocks(bad)


@pytest.mark.asyncio
async def test_grok_vision_sends_images_without_store(monkeypatch):
    seen = {}

    async def fake(messages, **kw):
        seen.update(kw, content=messages[-1]["content"])
        return _grok("Fût en bon état")

    monkeypatch.setattr(vision_mod, "grok_respond", fake)
    out = await _call(register_vision, "grok_vision",
                      {"prompt": "État du fût ?", "images": "https://x.example/a.jpg", "effort": "low"})
    assert "Fût en bon état" in out
    assert seen["store"] is False and seen["model"] == vision_mod.GROK_VISION_MODEL
    assert seen["content"][0] == {"type": "input_text", "text": "État du fût ?"}
    assert seen["content"][1]["type"] == "input_image"


def test_unwritable_data_dir_falls_back(monkeypatch, tmp_path):
    blocker = tmp_path / "fichier"
    blocker.write_text("x")
    monkeypatch.setenv("DATA_DIR", str(blocker / "sous-dossier"))   # parent = fichier → mkdir échoue
    store.init()
    assert not store.is_persistent() and store.db_path().parent.name == "data"
    store.save_note("p", "k", "v", "grok")
    store.db_path().unlink()
    monkeypatch.setattr(store, "_fallback_dir", None)


def test_unopenable_database_falls_back(monkeypatch, tmp_path):
    (tmp_path / "vol" / "bridge.sqlite3").mkdir(parents=True)   # un dossier à la place du fichier
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "vol"))
    store.init()
    assert not store.is_persistent()
    store.db_path().unlink()
    monkeypatch.setattr(store, "_fallback_dir", None)
