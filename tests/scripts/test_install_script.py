"""install.sh のテスト。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = ROOT / "scripts" / "install.sh"


def run_script(
    script: Path,
    args: list[str],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)

    return subprocess.run(
        ["bash", str(script), *args],
        cwd=ROOT,
        env=proc_env,
        capture_output=True,
        check=False,
        text=True,
    )


def test_install_script_prefetches_embedding_model() -> None:
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert "Prefetching embedding model cache" in content
    assert "prefetch_model()" in content
    assert "ensure_settings_json" in content
    assert "full default settings file" in content


def test_install_script_copies_settings_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """install.sh はテンプレート settings.json をそのまま配置する。"""
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))

    result = run_script(
        INSTALL_SCRIPT,
        ["--skip-python"],
        env={
            "HOME": str(home),
            "PATH": os.environ["PATH"],
        },
    )

    assert result.returncode == 0, result.stderr

    settings_path = home / ".devgear" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    template = json.loads((ROOT / "plugins" / "devgear" / "settings.json").read_text(encoding="utf-8"))

    assert settings == template
    # mem は sync.enabled / sync.postgres_url のみを保持
    assert set(settings["mem"].keys()) == {"sync"}
    assert set(settings["mem"]["sync"].keys()) == {"enabled", "postgres_url"}
    assert settings_path.stat().st_mode & 0o777 == 0o600


def test_install_script_leaves_existing_settings_json_untouched(tmp_path: Path) -> None:
    home = tmp_path / "home"
    settings_path = home / ".devgear" / "settings.json"
    settings_path.parent.mkdir(parents=True)

    original = json.dumps(
        {
            "project": {
                "git-hosting-service": "gitlab",
            },
            "custom": {
                "flag": True,
            },
        },
        indent=2,
    ) + "\n"
    settings_path.write_text(original, encoding="utf-8")

    result = run_script(
        INSTALL_SCRIPT,
        ["--skip-python"],
        env={
            "HOME": str(home),
            "PATH": os.environ["PATH"],
        },
    )

    assert result.returncode == 0, result.stderr
    assert settings_path.read_text(encoding="utf-8") == original
