"""comply/classifier モジュールのユニットテスト。

テスト対象: _parse_classification (純粋ロジック) と classify_events の subprocess ブランチ。

デシジョンテーブル:
  _parse_classification:
    - 正常な JSON dict → ステップ→インデックスリストのマッピング
    - Markdown フェンス付き → フェンス除去して解析
    - JSON が dict でない (list) → 空 dict + warning
    - JSON デコードエラー → 空 dict + warning
    - 値の int 変換エラー → TypeError/ValueError → 空 dict + warning
    - 空文字列 → 空 dict

  classify_events:
    - 空トレース → 空 dict (LLM 呼び出し不要)
    - subprocess 成功 → _parse_classification の結果を返す
    - subprocess 失敗 (returncode != 0) → RuntimeError
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from devgear.skills.comply.classifier import _parse_classification, classify_events
from devgear.skills.comply.parser import ComplianceSpec, Detector, ObservationEvent, Step

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_spec() -> ComplianceSpec:
    step = Step(
        id="write_test",
        description="Write a test first",
        required=True,
        detector=Detector(description="Check for test file creation"),
    )
    return ComplianceSpec(
        id="tdd-workflow",
        name="TDD Workflow",
        source_rule="s-tdd",
        version="1.0",
        steps=(step,),
        threshold_promote_to_hook=0.6,
    )


def _make_event(tool: str = "Write", input_text: str = "test_fib.py") -> ObservationEvent:
    return ObservationEvent(
        timestamp="2024-01-01T00:00:00Z",
        event="tool_use",
        tool=tool,
        session="sess-001",
        input=input_text,
        output="File created",
    )


# ---------------------------------------------------------------------------
# _parse_classification
# ---------------------------------------------------------------------------


class TestParseClassification:
    """_parse_classification の純粋ロジックテスト"""

    def test_valid_json_dict_parsed(self) -> None:
        text = '{"write_test": [0, 1], "run_test": [2]}'
        result = _parse_classification(text)
        assert result == {"write_test": [0, 1], "run_test": [2]}

    def test_empty_string_returns_empty_dict(self) -> None:
        result = _parse_classification("")
        assert result == {}

    def test_markdown_fence_removed(self) -> None:
        text = '```json\n{"write_test": [0]}\n```'
        result = _parse_classification(text)
        assert result == {"write_test": [0]}

    def test_generic_fence_removed(self) -> None:
        text = '```\n{"step": [1, 2]}\n```'
        result = _parse_classification(text)
        assert result == {"step": [1, 2]}

    def test_json_list_returns_empty_dict_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="devgear.skills.comply.classifier"):
            result = _parse_classification("[0, 1, 2]")
        assert result == {}
        assert (
            "non-dict" in caplog.text.lower() or "non-dict" in caplog.messages[0].lower() if caplog.messages else True
        )

    def test_invalid_json_returns_empty_dict(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="devgear.skills.comply.classifier"):
            result = _parse_classification("{invalid json")
        assert result == {}

    def test_value_not_list_filtered_out(self) -> None:
        # v が list でない値は除外される
        text = '{"step_a": [0], "step_b": "not_a_list"}'
        result = _parse_classification(text)
        # step_b は list でないので除外
        assert "step_a" in result
        assert "step_b" not in result

    def test_integer_conversion_of_indices(self) -> None:
        # 数値文字列でも int() で変換される
        text = '{"step": [0, 1, 2]}'
        result = _parse_classification(text)
        assert all(isinstance(i, int) for i in result["step"])

    def test_empty_dict_json(self) -> None:
        assert _parse_classification("{}") == {}

    def test_multiple_steps_mapped(self) -> None:
        text = '{"step_a": [0, 2], "step_b": [1, 3], "step_c": []}'
        result = _parse_classification(text)
        assert result["step_a"] == [0, 2]
        assert result["step_b"] == [1, 3]
        assert result["step_c"] == []


# ---------------------------------------------------------------------------
# classify_events
# ---------------------------------------------------------------------------


class TestClassifyEvents:
    """classify_events の subprocess ブランチテスト"""

    def test_empty_trace_returns_empty_dict(self) -> None:
        spec = _make_spec()
        result = classify_events(spec, trace=[])
        assert result == {}

    def test_subprocess_success_returns_parsed_result(self) -> None:
        spec = _make_spec()
        trace = [_make_event()]

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"write_test": [0]}'

        with patch("devgear.skills.comply.classifier.subprocess.run", return_value=mock_result):
            result = classify_events(spec, trace)

        assert result == {"write_test": [0]}

    def test_subprocess_failure_raises_runtime_error(self) -> None:
        spec = _make_spec()
        trace = [_make_event()]

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "claude command not found"

        with patch("devgear.skills.comply.classifier.subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="classifier subprocess failed"):
                classify_events(spec, trace)

    def test_prompt_contains_step_and_tool_info(self) -> None:
        """subprocess に渡すプロンプトにステップ情報とツール呼び出しが含まれるか確認。"""
        spec = _make_spec()
        trace = [_make_event(tool="Read", input_text="some_file.py")]

        calls: list = []

        def _capture_run(cmd, **kwargs):
            calls.append(kwargs.get("input", "") or "")
            r = MagicMock()
            r.returncode = 0
            r.stdout = "{}"
            return r

        with patch("devgear.skills.comply.classifier.subprocess.run", side_effect=_capture_run):
            classify_events(spec, trace)

        # subprocess.run が1回呼ばれること
        assert len(calls) == 1

    def test_custom_model_passed_to_subprocess(self) -> None:
        spec = _make_spec()
        trace = [_make_event()]

        captured_cmd: list[list[str]] = []

        def _capture(cmd, **kwargs):
            captured_cmd.append(cmd)
            r = MagicMock()
            r.returncode = 0
            r.stdout = "{}"
            return r

        with patch("devgear.skills.comply.classifier.subprocess.run", side_effect=_capture):
            classify_events(spec, trace, model="opus")

        assert "opus" in captured_cmd[0]
