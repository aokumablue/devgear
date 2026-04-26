"""LLMを用いて、ツール呼び出しをコンプライアンス手順に分類する。"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .parser import ComplianceSpec, ObservationEvent

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def classify_events(
    spec: ComplianceSpec,
    trace: list[ObservationEvent],
    model: str = "haiku",
) -> dict[str, list[int]]:
    """どのツール呼び出しがどのコンプライアンス手順に対応するかを分類する。

    単一のLLM呼び出しで {step_id: [event_indices]} を返す。
    """
    if not trace:
        return {}

    steps_desc = "\n".join(f"- {step.id}: {step.detector.description}" for step in spec.steps)

    tool_calls = "\n".join(
        f"[{i}] {event.tool}: input={event.input[:500]} output={event.output[:200]}" for i, event in enumerate(trace)
    )

    prompt_template = (PROMPTS_DIR / "classifier.md").read_text()
    prompt = prompt_template.replace("{steps_description}", steps_desc).replace("{tool_calls}", tool_calls)

    result = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(f"classifier subprocess failed (rc={result.returncode}): {result.stderr[:500]}")

    return _parse_classification(result.stdout)


def _parse_classification(text: str) -> dict[str, list[int]]:
    """LLMの分類出力を {step_id: [event_indices]} に変換する。"""
    text = text.strip()
    # Markdownのフェンスを除去
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    cleaned = "\n".join(lines)

    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            logger.warning("Classifier returned non-dict JSON: %s", type(parsed).__name__)
            return {}
        return {k: [int(i) for i in v] for k, v in parsed.items() if isinstance(v, list)}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("Failed to parse classification output: %s", e)
        return {}
