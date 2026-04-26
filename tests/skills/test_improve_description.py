"""Tests for the skill description improvement workflow."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import devgear.skills.utils as skill_utils
import pytest
from devgear.skills import improve_description as imp


def test_call_claude_builds_command_and_strips_env(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def fake_run(cmd, input, capture_output, text, env, timeout):  # noqa: ANN001
        seen["cmd"] = cmd
        seen["input"] = input
        seen["capture_output"] = capture_output
        seen["text"] = text
        seen["env"] = env
        seen["timeout"] = timeout
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("OTHER", "value")
    monkeypatch.setattr(imp.subprocess, "run", fake_run)

    assert imp._call_claude("prompt", "sonnet", timeout=42) == "ok"
    assert seen["cmd"] == ["claude", "-p", "--output-format", "text", "--model", "sonnet"]
    assert seen["input"] == "prompt"
    assert seen["capture_output"] is True
    assert seen["text"] is True
    assert seen["timeout"] == 42
    assert "CLAUDECODE" not in seen["env"]
    assert seen["env"]["OTHER"] == "value"


def test_call_claude_raises_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        imp.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="", stderr="boom"),
    )

    with pytest.raises(RuntimeError) as exc_info:
        imp._call_claude("prompt", None)

    assert "claude -p exited 2" in str(exc_info.value)
    assert "stderr: boom" in str(exc_info.value)


def test_improve_description_writes_transcript_without_rewrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "logs"
    eval_results = {
        "summary": {"passed": 1, "total": 2},
        "results": [
            {"query": "need file workflow", "should_trigger": True, "pass": False, "triggers": 0, "runs": 2},
            {"query": "avoid trigger", "should_trigger": False, "pass": False, "triggers": 1, "runs": 2},
        ],
    }
    history = [
        {
            "description": "old description",
            "train_passed": 1,
            "train_total": 2,
            "test_passed": 1,
            "test_total": 2,
            "results": [
                {"query": "previous", "pass": True, "triggers": 1, "runs": 1},
            ],
            "note": "previous attempt",
        }
    ]

    monkeypatch.setattr(
        imp,
        "_call_claude",
        lambda prompt, model, timeout=300: "<new_description>Better description</new_description>",
    )

    description = imp.improve_description(
        skill_name="sample-skill",
        skill_content="skill content",
        current_description="current description",
        eval_results=eval_results,
        history=history,
        model="sonnet",
        test_results={"summary": {"passed": 1, "total": 1}},
        log_dir=log_dir,
        iteration=7,
    )

    transcript = json.loads((log_dir / "improve_iter_7.json").read_text())

    assert description == "Better description"
    assert transcript["final_description"] == "Better description"
    assert transcript["char_count"] == len("Better description")
    assert transcript["over_limit"] is False
    assert "トリガー漏れ" in transcript["prompt"]
    assert "誤トリガー" in transcript["prompt"]
    assert "過去の試行" in transcript["prompt"]
    assert "previous attempt" in transcript["prompt"]
    assert transcript["response"] == "<new_description>Better description</new_description>"
    assert "rewrite_prompt" not in transcript


def test_improve_description_rewrites_when_description_is_too_long(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "logs"
    long_description = "x" * 1100
    calls = iter(
        [
            f"<new_description>{long_description}</new_description>",
            "<new_description>shortened description</new_description>",
        ]
    )

    monkeypatch.setattr(imp, "_call_claude", lambda prompt, model, timeout=300: next(calls))

    description = imp.improve_description(
        skill_name="sample-skill",
        skill_content="skill content",
        current_description="current description",
        eval_results={"summary": {"passed": 0, "total": 1}, "results": []},
        history=[],
        model="sonnet",
        log_dir=log_dir,
        iteration=8,
    )

    transcript = json.loads((log_dir / "improve_iter_8.json").read_text())

    assert description == "shortened description"
    assert transcript["final_description"] == "shortened description"
    assert transcript["over_limit"] is True
    assert transcript["rewrite_char_count"] == len("shortened description")
    assert "over the 1024-character hard limit" in transcript["rewrite_prompt"]
    assert transcript["rewrite_description"] == "shortened description"


def test_main_rejects_missing_skill_md(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    skill_dir = tmp_path / "skill"
    eval_results = tmp_path / "eval.json"
    eval_results.write_text(json.dumps({"description": "old", "summary": {"passed": 0, "failed": 1, "total": 1}, "results": []}))
    monkeypatch.setattr(sys, "argv", ["improve_description.py", "--eval-results", str(eval_results), "--skill-path", str(skill_dir), "--model", "sonnet"])

    with pytest.raises(SystemExit) as exc_info:
        imp.main()

    assert exc_info.value.code == 1
    assert "SKILL.md が見つかりません" in capsys.readouterr().err


def test_main_generates_updated_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: sample-skill\ndescription: old\n---\nBody\n")
    eval_results = tmp_path / "eval.json"
    history = tmp_path / "history.json"
    eval_results.write_text(
        json.dumps(
            {
                "description": "old description",
                "summary": {"passed": 1, "failed": 1, "total": 2},
                "results": [{"query": "x", "should_trigger": True, "pass": False, "triggers": 0, "runs": 1}],
            }
        )
    )
    history.write_text(json.dumps([{"description": "previous", "passed": 0, "failed": 1, "total": 1, "results": []}]))

    seen = {}

    def fake_improve_description(**kwargs):
        seen.update(kwargs)
        return "new description"

    def fake_parse_skill_md(path):
        return "sample-skill", "old", "content"

    monkeypatch.setattr(imp, "improve_description", fake_improve_description)
    monkeypatch.setattr(imp, "parse_skill_md", fake_parse_skill_md)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "improve_description.py",
            "--eval-results",
            str(eval_results),
            "--skill-path",
            str(skill_dir),
            "--history",
            str(history),
            "--model",
            "sonnet",
            "--verbose",
        ],
    )

    imp.main()

    captured = capsys.readouterr()
    output = json.loads(captured.out)

    assert seen["skill_name"] == "sample-skill"
    assert seen["current_description"] == "old description"
    assert seen["model"] == "sonnet"
    assert "現在の説明: old description" in captured.err
    assert output["description"] == "new description"
    assert output["history"][-1]["description"] == "old description"
    assert output["history"][-1]["results"] == [{"query": "x", "should_trigger": True, "pass": False, "triggers": 0, "runs": 1}]


def test_main_module_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: sample\ndescription: old\n---\nBody\n")
    eval_results = tmp_path / "eval.json"
    eval_results.write_text(
        json.dumps(
            {
                "description": "old description",
                "summary": {"passed": 1, "failed": 0, "total": 1},
                "results": [],
            }
        )
    )

    def fake_run(*args, **kwargs):  # noqa: ANN001
        return SimpleNamespace(returncode=0, stdout="<new_description>From entrypoint</new_description>", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(skill_utils, "parse_skill_md", lambda path: ("sample", "old", "content"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "improve_description.py",
            "--eval-results",
            str(eval_results),
            "--skill-path",
            str(skill_dir),
            "--model",
            "sonnet",
        ],
    )

    runpy.run_module("devgear.skills.improve_description", run_name="__main__")
