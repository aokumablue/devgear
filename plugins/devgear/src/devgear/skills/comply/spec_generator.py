"""LLMを用いて、スキルファイルからコンプライアンス仕様を生成する。"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml

from .parser import ComplianceSpec, parse_spec
from .utils import extract_yaml

PROMPTS_DIR = Path(__file__).parent / "prompts"


def generate_spec(
    skill_path: Path,
    model: str = "haiku",
    max_retries: int = 2,
) -> ComplianceSpec:
    """スキル／ルールファイルからコンプライアンス仕様を生成する。

    spec_generator プロンプトで claude -p を呼び出し、YAML出力を解析する。
    YAML解析エラー時は、エラーフィードバックを付けて再試行する。
    """
    skill_content = skill_path.read_text()
    prompt_template = (PROMPTS_DIR / "spec_generator.md").read_text()
    base_prompt = prompt_template.replace("{skill_content}", skill_content)

    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        prompt = base_prompt
        if attempt > 0 and last_error is not None:
            prompt += (
                f"\n\nPREVIOUS ATTEMPT FAILED with YAML parse error:\n"
                f"{last_error}\n\n"
                f"Please fix the YAML. Remember to quote all string values "
                f'that contain colons, e.g.: description: "Use type: description format"'
            )

        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise RuntimeError(f"claude -p failed: {result.stderr}")

        raw_yaml = extract_yaml(result.stdout)

        tmp_path = None
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
        ) as f:
            f.write(raw_yaml)
            tmp_path = Path(f.name)

        try:
            return parse_spec(tmp_path)
        except (yaml.YAMLError, KeyError, TypeError) as e:
            last_error = e
            if attempt == max_retries:
                raise
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    raise RuntimeError("unreachable")
