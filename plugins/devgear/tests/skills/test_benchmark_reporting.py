"""Tests for benchmark aggregation and report generation helpers."""

from __future__ import annotations

import io
import json
import runpy
import sys
from datetime import UTC
from datetime import datetime as real_datetime
from pathlib import Path

import pytest

from devgear.skills import aggregate_benchmark as ab
from devgear.skills import generate_report as gr


def _result(query: str, should_trigger: bool, passed: bool, triggers: int, runs: int) -> dict[str, object]:
    return {
        "query": query,
        "should_trigger": should_trigger,
        "pass": passed,
        "triggers": triggers,
        "runs": runs,
    }


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def test_generate_html_highlights_best_row_and_scores() -> None:
    data = {
        "history": [
            {
                "iteration": 1,
                "description": "first pass",
                "train_passed": 4,
                "train_total": 4,
                "test_passed": 4,
                "test_total": 4,
                "train_results": [
                    _result("train-pass", True, True, 2, 2),
                    _result("train-miss", False, True, 0, 2),
                ],
                "test_results": [
                    _result("test-pass", True, True, 2, 2),
                    _result("test-miss", False, True, 0, 2),
                ],
            },
            {
                "iteration": 2,
                "description": "second <script>",
                "train_passed": 3,
                "train_total": 4,
                "test_passed": 3,
                "test_total": 4,
                "train_results": [
                    _result("train-pass", True, True, 1, 2),
                    _result("train-miss", False, True, 0, 2),
                ],
                "test_results": [
                    _result("test-pass", True, True, 1, 2),
                    _result("test-miss", False, True, 0, 2),
                ],
            },
            {
                "iteration": 3,
                "description": "third",
                "train_passed": 1,
                "train_total": 4,
                "test_passed": 1,
                "test_total": 4,
                "train_results": [
                    _result("train-pass", True, False, 0, 2),
                    _result("train-miss", False, False, 1, 2),
                ],
                "test_results": [
                    _result("test-pass", True, False, 0, 2),
                    _result("test-miss", False, False, 1, 2),
                ],
            },
        ],
        "original_description": "orig",
        "best_description": "best",
        "best_score": 0.75,
        "best_test_score": 0.75,
        "iterations_run": 3,
        "train_size": 2,
        "test_size": 2,
    }

    html_output = gr.generate_html(data, auto_refresh=True, skill_name="sample")

    assert '<meta http-equiv="refresh" content="5">' in html_output
    assert "<title>sample — スキル説明の最適化</title>" in html_output
    assert html_output.count('class="best-row"') == 1
    assert "score-good" in html_output
    assert "score-ok" in html_output
    assert "score-bad" in html_output
    assert "second &lt;script&gt;" in html_output
    assert "train-pass" in html_output
    assert "test-miss" in html_output


def test_generate_html_without_test_queries_uses_train_score() -> None:
    data = {
        "history": [
            {
                "iteration": 1,
                "description": "train only",
                "passed": 2,
                "total": 4,
                "train_results": [
                    _result("train-pass", True, True, 2, 2),
                    _result("train-miss", False, True, 0, 2),
                ],
            }
        ],
        "original_description": "orig",
        "best_description": "best",
        "best_score": 0.5,
        "iterations_run": 1,
        "train_size": 2,
        "test_size": 0,
    }

    html_output = gr.generate_html(data)

    assert 'class="best-row"' in html_output
    assert '<th class="test-col"' not in html_output
    assert "train only" in html_output
    assert "score-good" in html_output


def test_generate_report_main_reads_stdin_and_writes_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    output_path = tmp_path / "report.html"
    payload = {
        "history": [
            {
                "iteration": 1,
                "description": "stdin",
                "passed": 2,
                "total": 2,
                "train_results": [_result("train", True, True, 1, 1)],
            }
        ],
        "original_description": "orig",
        "best_description": "best",
        "best_score": 1.0,
        "iterations_run": 1,
        "train_size": 1,
        "test_size": 0,
    }

    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, "argv", ["generate_report.py", "-", "-o", str(output_path), "--skill-name", "sample"])

    gr.main()

    assert output_path.exists()
    assert "レポートを書き出しました" in capsys.readouterr().err
    assert "sample — スキル説明の最適化" in output_path.read_text()


def test_generate_report_main_reads_file_and_writes_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    input_path = tmp_path / "input.json"
    payload = {
        "history": [
            {
                "iteration": 1,
                "description": "file",
                "passed": 1,
                "total": 1,
                "train_results": [_result("train", True, True, 1, 1)],
            }
        ],
        "original_description": "orig",
        "best_description": "best",
        "best_score": 1.0,
        "iterations_run": 1,
        "train_size": 1,
        "test_size": 0,
    }
    _write_json(input_path, payload)
    monkeypatch.setattr(sys, "argv", ["generate_report.py", str(input_path), "--skill-name", "sample"])

    gr.main()

    stdout = capsys.readouterr().out
    assert "<html>" in stdout
    assert "sample — スキル説明の最適化" in stdout


def test_generate_report_module_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "report.html"
    payload = {
        "history": [
            {
                "iteration": 1,
                "description": "file",
                "passed": 1,
                "total": 1,
                "train_results": [_result("train", True, True, 1, 1)],
            }
        ],
        "original_description": "orig",
        "best_description": "best",
        "best_score": 1.0,
        "iterations_run": 1,
        "train_size": 1,
        "test_size": 0,
    }
    _write_json(input_path, payload)
    monkeypatch.setattr(sys, "argv", ["generate_report.py", str(input_path), "-o", str(output_path), "--skill-name", "sample"])

    runpy.run_module("devgear.skills.generate_report", run_name="__main__")

    assert output_path.exists()


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([], {"mean": 0.0, "stddev": 0.0, "min": 0.0, "max": 0.0}),
        ([2.5], {"mean": 2.5, "stddev": 0.0, "min": 2.5, "max": 2.5}),
        ([1.0, 2.0, 3.0], {"mean": 2.0, "stddev": 1.0, "min": 1.0, "max": 3.0}),
    ],
)
def test_calculate_stats(values: list[float], expected: dict[str, float]) -> None:
    assert ab.calculate_stats(values) == expected


def test_load_run_results_collects_runs_and_warnings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    benchmark_dir = tmp_path / "benchmark"
    eval0 = benchmark_dir / "eval-0"
    eval1 = benchmark_dir / "eval-1"
    eval0.mkdir(parents=True)
    eval1.mkdir(parents=True)

    _write_json(eval0 / "eval_metadata.json", {"eval_id": 12})

    with_skill_run1 = eval0 / "with_skill" / "run-1"
    with_skill_run1.mkdir(parents=True)
    _write_json(
        with_skill_run1 / "grading.json",
        {
            "summary": {"pass_rate": 0.8, "passed": 8, "failed": 2, "total": 10},
            "timing": {"total_duration_seconds": 0.0},
            "execution_metrics": {
                "total_tool_calls": 5,
                "output_chars": 123,
                "errors_encountered": 1,
            },
            "expectations": [
                {"text": "ok", "passed": True, "evidence": "x"},
                {"text": "missing passed"},
            ],
            "user_notes_summary": {
                "uncertainties": ["u1"],
                "needs_review": ["u2"],
                "workarounds": ["u3"],
            },
        },
    )
    _write_json(with_skill_run1 / "timing.json", {"total_duration_seconds": 12.5, "total_tokens": 77})

    (eval0 / "with_skill" / "run-2").mkdir(parents=True)
    (eval0 / "with_skill" / "run-2" / "grading.json").write_text("{")

    without_skill_run1 = eval0 / "without_skill" / "run-1"
    without_skill_run1.mkdir(parents=True)
    _write_json(
        without_skill_run1 / "grading.json",
        {
            "summary": {"pass_rate": 0.5, "passed": 5, "failed": 5, "total": 10},
            "timing": {},
            "execution_metrics": {
                "total_tool_calls": 2,
                "output_chars": 99,
                "errors_encountered": 0,
            },
            "expectations": [],
            "user_notes_summary": {},
        },
    )
    (eval0 / "without_skill" / "run-2").mkdir(parents=True)

    (eval0 / "inputs").mkdir()
    (eval0 / "inputs" / "placeholder.txt").write_text("skip")

    new_skill_run1 = eval1 / "new_skill" / "run-1"
    new_skill_run1.mkdir(parents=True)
    _write_json(
        new_skill_run1 / "grading.json",
        {
            "summary": {"pass_rate": 0.3, "passed": 3, "failed": 7, "total": 10},
            "timing": {"total_duration_seconds": 3.2},
            "execution_metrics": {
                "total_tool_calls": 1,
                "output_chars": 11,
                "errors_encountered": 0,
            },
            "expectations": [],
            "user_notes_summary": {},
        },
    )

    results = ab.load_run_results(benchmark_dir)
    output = capsys.readouterr().out

    assert "grading.json が見つかりません" in output
    assert "JSON が不正です" in output
    assert "expectation に必須フィールドがありません" in output
    assert results["with_skill"][0]["eval_id"] == 12
    assert results["with_skill"][0]["run_number"] == 1
    assert results["with_skill"][0]["time_seconds"] == 12.5
    assert results["with_skill"][0]["tokens"] == 77
    assert results["with_skill"][0]["tool_calls"] == 5
    assert results["with_skill"][0]["errors"] == 1
    assert results["with_skill"][0]["notes"] == ["u1", "u2", "u3"]
    assert results["without_skill"][0]["tokens"] == 99
    assert results["new_skill"][0]["eval_id"] == 1


def test_load_run_results_returns_empty_when_no_eval_dirs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ab.load_run_results(tmp_path) == {}
    assert "eval ディレクトリが" in capsys.readouterr().out


def test_load_run_results_handles_invalid_metadata_and_timing_json(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmark"
    eval0 = benchmark_dir / "eval-alpha"
    eval1 = benchmark_dir / "eval-beta"
    run0 = eval0 / "with_skill" / "run-1"
    run1 = eval1 / "without_skill" / "run-1"

    run0.mkdir(parents=True)
    run1.mkdir(parents=True)
    (eval0 / "eval_metadata.json").write_text("{")
    _write_json(
        run0 / "grading.json",
        {
            "summary": {"pass_rate": 0.1, "passed": 1, "failed": 9, "total": 10},
            "timing": {"total_duration_seconds": 0.0},
            "execution_metrics": {"total_tool_calls": 1, "output_chars": 11, "errors_encountered": 0},
            "expectations": [],
            "user_notes_summary": {},
        },
    )
    (run0 / "timing.json").write_text("{")
    _write_json(
        run1 / "grading.json",
        {
            "summary": {"pass_rate": 0.2, "passed": 2, "failed": 8, "total": 10},
            "timing": {"total_duration_seconds": 4.0},
            "execution_metrics": {"total_tool_calls": 2, "output_chars": 22, "errors_encountered": 0},
            "expectations": [],
            "user_notes_summary": {},
        },
    )

    results = ab.load_run_results(benchmark_dir)

    assert results["with_skill"][0]["eval_id"] == 0
    assert results["with_skill"][0]["time_seconds"] == 0.0
    assert results["with_skill"][0]["tokens"] == 11
    assert results["without_skill"][0]["eval_id"] == 1


def test_aggregate_results_with_empty_config() -> None:
    results = {
        "with_skill": [{"pass_rate": 0.75, "time_seconds": 2.0, "tokens": 10}],
        "without_skill": [],
    }

    summary = ab.aggregate_results(results)

    assert summary["with_skill"]["pass_rate"] == {"mean": 0.75, "stddev": 0.0, "min": 0.75, "max": 0.75}
    assert summary["without_skill"]["tokens"] == {"mean": 0, "stddev": 0, "min": 0, "max": 0}
    assert summary["delta"] == {"pass_rate": "+0.75", "time_seconds": "+2.0", "tokens": "+10"}


def test_aggregate_results_single_config_uses_empty_baseline() -> None:
    results = {"solo": [{"pass_rate": 0.4, "time_seconds": 1.5, "tokens": 7}]}

    summary = ab.aggregate_results(results)

    assert summary["solo"]["pass_rate"]["mean"] == 0.4
    assert summary["delta"] == {"pass_rate": "+0.40", "time_seconds": "+1.5", "tokens": "+7"}


class FixedDatetime:
    @staticmethod
    def now(tz=None):  # noqa: ANN001
        return real_datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_generate_benchmark_and_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ab,
        "load_run_results",
        lambda benchmark_dir: {
            "with_skill": [{"eval_id": 3, "run_number": 1, "pass_rate": 0.9, "passed": 9, "failed": 1, "total": 10, "time_seconds": 1.2, "tokens": 50, "tool_calls": 2, "errors": 0, "expectations": [], "notes": []}],
            "without_skill": [{"eval_id": 5, "run_number": 1, "pass_rate": 0.2, "passed": 2, "failed": 8, "total": 10, "time_seconds": 2.4, "tokens": 100, "tool_calls": 4, "errors": 1, "expectations": [], "notes": []}],
        },
    )
    monkeypatch.setattr(ab, "datetime", FixedDatetime)

    benchmark = ab.generate_benchmark(Path("/tmp/benchmark"), "skill", "/skill")
    markdown = ab.generate_markdown({**benchmark, "notes": ["note one", "note two"]})

    assert benchmark["metadata"]["skill_name"] == "skill"
    assert benchmark["metadata"]["skill_path"] == "/skill"
    assert benchmark["metadata"]["timestamp"] == "2024-01-02T03:04:05Z"
    assert benchmark["metadata"]["evals_run"] == [3, 5]
    assert len(benchmark["runs"]) == 2
    assert benchmark["run_summary"]["delta"]["pass_rate"] == "+0.70"
    assert "# スキルベンチマーク: skill" in markdown
    assert "| 合格率 | 90% ± 0% | 20% ± 0% | +0.70 |" in markdown
    assert "## 備考" in markdown
    assert "- note one" in markdown


def test_aggregate_benchmark_main_missing_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(sys, "argv", ["aggregate_benchmark.py", str(missing)])

    with pytest.raises(SystemExit) as exc_info:
        ab.main()

    assert exc_info.value.code == 1
    assert "ディレクトリが見つかりません" in capsys.readouterr().out


def test_aggregate_benchmark_main_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    benchmark_dir = tmp_path / "benchmark"
    run1 = benchmark_dir / "eval-0" / "with_skill" / "run-1"
    run2 = benchmark_dir / "eval-0" / "without_skill" / "run-1"
    run1.mkdir(parents=True)
    run2.mkdir(parents=True)

    _write_json(
        run1 / "grading.json",
        {
            "summary": {"pass_rate": 1.0, "passed": 1, "failed": 0, "total": 1},
            "timing": {"total_duration_seconds": 1.0},
            "execution_metrics": {"total_tool_calls": 1, "output_chars": 10, "errors_encountered": 0},
            "expectations": [],
            "user_notes_summary": {},
        },
    )
    _write_json(
        run2 / "grading.json",
        {
            "summary": {"pass_rate": 0.0, "passed": 0, "failed": 1, "total": 1},
            "timing": {"total_duration_seconds": 2.0},
            "execution_metrics": {"total_tool_calls": 2, "output_chars": 20, "errors_encountered": 1},
            "expectations": [],
            "user_notes_summary": {},
        },
    )

    monkeypatch.setattr(sys, "argv", ["aggregate_benchmark.py", str(benchmark_dir), "--skill-name", "skill", "--skill-path", "/skill"])
    monkeypatch.setattr(ab, "datetime", FixedDatetime)

    ab.main()

    json_path = benchmark_dir / "benchmark.json"
    md_path = benchmark_dir / "benchmark.md"
    stdout = capsys.readouterr().out

    assert json_path.exists()
    assert md_path.exists()
    assert "生成しました:" in stdout
    assert "サマリー:" in stdout
    assert "With Skill" in stdout
    assert "Without Skill" in stdout
    assert "差分:          +1.00" in stdout


def test_aggregate_benchmark_module_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark_dir = tmp_path / "benchmark"
    run_dir = benchmark_dir / "eval-0" / "with_skill" / "run-1"
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "grading.json",
        {
            "summary": {"pass_rate": 1.0, "passed": 1, "failed": 0, "total": 1},
            "timing": {"total_duration_seconds": 1.0},
            "execution_metrics": {"total_tool_calls": 1, "output_chars": 10, "errors_encountered": 0},
            "expectations": [],
            "user_notes_summary": {},
        },
    )
    monkeypatch.setattr(sys, "argv", ["aggregate_benchmark.py", str(benchmark_dir), "--skill-name", "skill"])

    runpy.run_module("devgear.skills.aggregate_benchmark", run_name="__main__")

    assert (benchmark_dir / "benchmark.json").exists()
    assert (benchmark_dir / "benchmark.md").exists()
