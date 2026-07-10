"""Tests for the Dev Agent (tool-use loop) and its confined dev tools."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from kaos.contracts.context import Context
from kaos.contracts.llm import Message
from kaos.plugins.agents.dev_agent import DevAgent, _extract_json
from kaos.plugins.tools import default_dev_tools
from kaos.plugins.tools.dev_tools import (
    ListDirTool,
    ReadFileTool,
    RunCommandTool,
    SearchCodeTool,
)


class ScriptedLLM:
    """An LLMProvider double that replays a fixed list of responses."""

    name = "scripted"

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self.calls: list[Sequence[Message]] = []

    async def complete(self, messages: Sequence[Message], **_options: object) -> str:
        self.calls.append(list(messages))
        if self._responses:
            return self._responses.pop(0)
        return '{"action":"final","answer":"done"}'


# ---- _extract_json ----


def test_extract_json_ignores_surrounding_text() -> None:
    assert _extract_json('blah {"action":"final","answer":"x"} tail') == {
        "action": "final",
        "answer": "x",
    }


def test_extract_json_handles_braces_in_strings() -> None:
    assert _extract_json('{"a":"has } brace"}') == {"a": "has } brace"}


def test_extract_json_returns_none_without_object() -> None:
    assert _extract_json("no json here") is None


# ---- Dev tools ----


def test_read_file_within_root(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hola mundo", encoding="utf-8")
    tool = ReadFileTool(tmp_path)
    out = asyncio.run(tool.run({"path": "hello.txt"}))
    assert out == "hola mundo"


def test_read_file_rejects_traversal(tmp_path: Path) -> None:
    tool = ReadFileTool(tmp_path)
    out = asyncio.run(tool.run({"path": "../secret"}))
    assert "fuera del workspace" in out


def test_list_dir_lists_entries(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    out = asyncio.run(ListDirTool(tmp_path).run({"path": "."}))
    assert "a.py" in out and "sub/" in out


def test_search_code_finds_matches(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("x = 1  # TODO revisar\n", encoding="utf-8")
    out = asyncio.run(SearchCodeTool(tmp_path).run({"query": "TODO", "ext": ".py"}))
    assert "mod.py:1:" in out and "TODO" in out


def test_run_command_rejects_unlisted(tmp_path: Path) -> None:
    tool = RunCommandTool(tmp_path)  # default allowlist (read-only)
    out = asyncio.run(tool.run({"command": "rm -rf /"}))
    assert "no permitido" in out


def test_run_command_runs_allowed(tmp_path: Path) -> None:
    tool = RunCommandTool(tmp_path, allowed=[("git", "--version")])
    out = asyncio.run(tool.run({"command": "git --version"}))
    assert "git version" in out.lower()


# ---- Dev Agent loop ----


def test_dev_agent_uses_tool_then_finalizes(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hola mundo", encoding="utf-8")
    llm = ScriptedLLM(
        [
            '{"action":"tool","tool":"read_file","args":{"path":"hello.txt"}}',
            '{"action":"final","answer":"# Informe\\nleí el archivo"}',
        ]
    )
    agent = DevAgent(llm, default_dev_tools(tmp_path), max_steps=5)
    context = Context(workspace="dev:test", params={"task": "leé hello.txt"})

    artifacts = asyncio.run(agent.run(context))
    assert len(artifacts) == 1
    art = artifacts[0]
    assert art.kind == "dev.session"
    assert art.produced_by == "dev-agent"
    assert "leí el archivo" in art.content["answer"]
    # The tool actually ran and its observation was captured.
    steps = art.content["steps"]
    read_steps = [s for s in steps if s.get("tool") == "read_file"]
    assert read_steps and "hola mundo" in read_steps[0]["observation"]
    # The rendered summary is dashboard-friendly.
    assert "Dev Agent" in art.content["summary"]
    assert "read_file" in art.content["summary"]


def test_dev_agent_forces_final_on_step_limit(tmp_path: Path) -> None:
    # Always ask for a tool; never finalize within the limit.
    llm = ScriptedLLM(
        [
            '{"action":"tool","tool":"list_dir","args":{}}',
            '{"action":"tool","tool":"list_dir","args":{}}',
            '{"action":"final","answer":"resumen forzado"}',
        ]
    )
    agent = DevAgent(llm, default_dev_tools(tmp_path), max_steps=2)
    context = Context(workspace="dev:test", params={"task": "explorá"})

    art = asyncio.run(agent.run(context))[0]
    assert art.content["answer"] == "resumen forzado"
    # Two tool steps were taken before the forced synthesis.
    assert art.content["step_count"] == 2


def test_dev_agent_no_task_returns_nothing(tmp_path: Path) -> None:
    agent = DevAgent(ScriptedLLM([]), default_dev_tools(tmp_path))
    art = asyncio.run(agent.run(Context(workspace="dev:test")))
    assert art == []


def test_dev_agent_rejects_premature_final(tmp_path: Path) -> None:
    # The model tries to finalize immediately; the agent must push it to use a
    # tool first, so small models inspect instead of hallucinating.
    (tmp_path / "hello.txt").write_text("hola mundo", encoding="utf-8")
    llm = ScriptedLLM(
        [
            '{"action":"final","answer":"inventado sin mirar"}',
            '{"action":"tool","tool":"read_file","args":{"path":"hello.txt"}}',
            '{"action":"final","answer":"# Informe\\ncontenido verificado"}',
        ]
    )
    agent = DevAgent(llm, default_dev_tools(tmp_path), max_steps=5)
    art = asyncio.run(agent.run(Context(workspace="dev:test", params={"task": "leé"})))[0]
    assert "contenido verificado" in art.content["answer"]
    assert art.content["step_count"] == 1  # exactly one tool call happened
    # The premature final was recorded as rejected.
    assert any(s.get("note", "").startswith("final rechazado") for s in art.content["steps"])


