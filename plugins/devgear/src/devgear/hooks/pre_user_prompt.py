"""UserPromptSubmit フック — Slim 圧縮ルールをコンテキストに注入する。

Slim が有効な場合、毎プロンプトで SKILL.md の内容を additionalContext に追加する。
常に終了コード 0 を返す。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from devgear.hooks.hook_common import parse_json_object, read_raw_stdin, write_stderr, write_stdout
from devgear.mem.settings import Settings, SlimSettings

# SKILL.md のパス（このファイルから相対解決）
_SKILL_PATH = Path(__file__).parents[4] / "skills" / "s-slim" / "SKILL.md"


def _load_slim_settings() -> SlimSettings:
    """Settings から SlimSettings を読み込む。失敗時はデフォルトを返す。"""
    try:
        return Settings.load().slim
    except Exception as e:
        write_stderr(f"[Slim] settings load failed: {e}\n")
        return SlimSettings()


def _load_skill_content() -> str:
    """SKILL.md を読み込む。ファイルが存在しないか読み込み失敗時は空文字を返す。"""
    if not _SKILL_PATH.exists():
        return ""
    try:
        return _SKILL_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def evaluate(raw_input: str, settings: SlimSettings | None = None) -> str:
    """UserPromptSubmit フックの評価処理。

    Args:
        raw_input: フックに渡された生の入力 JSON 文字列。
        settings: SlimSettings。None の場合は Settings.load() から読み込む。

    Returns:
        additionalContext を含む JSON 文字列、または空文字列（変更なしの場合）。
    """
    if settings is None:
        settings = _load_slim_settings()

    if not settings.enabled:
        return ""

    data = parse_json_object(raw_input)
    if data is None:
        return ""

    context = _load_skill_content()
    if not context:
        return ""

    payload = {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": context,
    }
    return json.dumps(payload, ensure_ascii=False)


def main() -> int:
    """UserPromptSubmit フックのエントリポイント。

    Returns:
        終了コード（0: 常に成功）。
    """
    raw = read_raw_stdin()
    try:
        output = evaluate(raw)
    except Exception as e:
        write_stderr(f"[Slim] unexpected error: {e}\n")
        output = ""

    if output:
        write_stdout(output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
