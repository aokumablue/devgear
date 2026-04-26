"""LLMを用いて、スキルと仕様からプレッシャーシナリオを生成する。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from .utils import extract_yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Scenario:
    id: str
    level: int
    level_name: str
    description: str
    prompt: str
    setup_commands: tuple[str, ...]


def generate_scenarios(
    skill_path: Path,
    spec_yaml: str,
    model: str = "haiku",
) -> list[Scenario]:
    """プロンプト厳格度を段階的に下げた3つのシナリオを生成する。

    scenario_generator プロンプトで claude -p を呼び出し、YAML出力を解析する。
    """
    skill_content = skill_path.read_text()
    prompt_template = (PROMPTS_DIR / "scenario_generator.md").read_text()
    prompt = prompt_template.replace("{skill_content}", skill_content).replace("{spec_yaml}", spec_yaml)

    result = subprocess.run(
        ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed: {result.stderr}")

    if not result.stdout.strip():
        raise RuntimeError("claude -p returned empty output")

    raw_yaml = extract_yaml(result.stdout)
    parsed = yaml.safe_load(raw_yaml)

    scenarios: list[Scenario] = []
    for s in parsed["scenarios"]:
        scenarios.append(
            Scenario(
                id=s["id"],
                level=s["level"],
                level_name=s["level_name"],
                description=s["description"],
                prompt=s["prompt"].strip(),
                setup_commands=tuple(s.get("setup_commands", [])),
            )
        )

    return sorted(scenarios, key=lambda s: s.level)
