"""install.sh のテスト。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
INSTALL_SCRIPT = ROOT / "plugins" / "devgear" / "install.sh"
INSTALL_DEV_SCRIPT = ROOT / "plugins" / "devgear" / "install-dev.sh"


def run_script(
    script: Path,
    args: list[str],
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """指定したシェルスクリプトを bash で実行して結果を返す。"""
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


def write_exec(path: Path, content: str) -> None:
    """実行可能なシェルスクリプトを書き込む。"""
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def write_fake_python(path: Path, log_path: Path) -> None:
    """install.sh の呼び出しを記録する python3 スタブを書き込む。"""
    write_exec(
        path,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"REAL_PYTHON={sys.executable!r}\n"
        f"LOG_PATH={str(log_path)!r}\n"
        'if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then\n'
        '  if [[ "${3:-}" == "--help" ]]; then\n'
        "    exit 0\n"
        "  fi\n"
        '  target="${3:-}"\n'
        '  mkdir -p "${target}/bin"\n'
        '  ln -sf "$0" "${target}/bin/python3"\n'
        '  ln -sf "$0" "${target}/bin/python3.12"\n'
        '  ln -sf "$0" "${target}/bin/python3.13"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then\n'
        '  echo "pip:${*:3}" >> "${LOG_PATH}"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "-m" && "${2:-}" == "ensurepip" ]]; then\n'
        '  echo "ensurepip:${*:3}" >> "${LOG_PATH}"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "-m" && "${2:-}" == "devgear.mem" && "${3:-}" == "setup" ]]; then\n'
        '  echo "memsetup:${*:3}" >> "${LOG_PATH}"\n'
        "  exit 0\n"
        "fi\n"
        'if [[ "${1:-}" == "-" ]]; then\n'
        "  script=$(cat)\n"
        '  if [[ "${script}" == *"prefetch_model()"* ]]; then\n'
        '    echo "prefetch" >> "${LOG_PATH}"\n'
        "    exit 0\n"
        "  fi\n"
        '  printf "%s" "${script}" | "${REAL_PYTHON}" - "${@:2}"\n'
        "  exit $?\n"
        "fi\n"
        'exec "${REAL_PYTHON}" "$@"\n',
    )


def prepare_temp_repo(tmp_path: Path) -> Path:
    """テスト用の最小リポジトリ構造を tmp_path に構築して返す。"""
    repo = tmp_path / "repo"
    plugin_dir = repo / "plugins" / "devgear"
    plugin_dir.mkdir(parents=True)
    shutil.copy2(ROOT / "plugins" / "devgear" / "install.sh", plugin_dir / "install.sh")
    shutil.copy2(ROOT / "plugins" / "devgear" / "install-dev.sh", plugin_dir / "install-dev.sh")
    shutil.copy2(ROOT / "plugins" / "devgear" / "settings.json", plugin_dir / "settings.json")
    shutil.copy2(ROOT / "plugins" / "devgear" / "pyproject.toml", plugin_dir / "pyproject.toml")
    return repo


def test_install_script_is_user_facing_only() -> None:
    """install.sh がユーザ向け処理のみを持ち、開発者向け依存を含まないこと。"""
    content = INSTALL_SCRIPT.read_text(encoding="utf-8")

    assert 'exec "${SCRIPT_DIR}/install-dev.sh"' in content
    assert "prefetch_model()" in content
    assert "torch>=2.0" in content
    assert "psycopg[binary]" in content
    assert "ruff" not in content
    assert "vulture" not in content


def test_install_dev_script_contains_developer_extras() -> None:
    """install-dev.sh が install.sh を呼び出し、開発者向け依存を追加すること。"""
    content = INSTALL_DEV_SCRIPT.read_text(encoding="utf-8")

    assert "torch>=2.0" not in content
    assert "psycopg[binary]" not in content
    assert "prefetch_model()" not in content
    assert 'bash "${SCRIPT_DIR}/install.sh"' in content
    assert "[dev]" in content
    assert "ruff" in content
    assert "vulture" in content


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
    """既存の settings.json が存在する場合は上書きせずそのまま保持すること。"""
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


def test_install_dev_script_runs_user_and_dev_steps(tmp_path: Path) -> None:
    """開発者向けスクリプトがユーザ向け導入の後に追加導入を行うこと。"""
    repo = prepare_temp_repo(tmp_path)
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home.mkdir()
    log_path = tmp_path / "python.log"

    write_fake_python(bin_dir / "python3", log_path)
    write_fake_python(bin_dir / "python3.12", log_path)
    write_fake_python(bin_dir / "python3.13", log_path)

    result = run_script(
        repo / "plugins" / "devgear" / "install-dev.sh",
        ["--repo-root", str(repo / "plugins" / "devgear")],
        env={
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (home / ".devgear" / "settings.json").exists()
    assert (repo / "plugins" / "devgear" / ".venv" / "bin" / "python3").exists()

    log = log_path.read_text(encoding="utf-8")
    log_lines = log.splitlines()
    editable_idx = next(i for i, line in enumerate(log_lines) if line.startswith("pip:install -e"))
    torch_idx = next(i for i, line in enumerate(log_lines) if "torch>=2.0" in line)

    assert "pip:install --upgrade pip wheel" in log
    assert "pip:install -e" in log
    assert "torch>=2.0" in log
    assert "--index-url https://download.pytorch.org/whl/cpu" in log_lines[torch_idx]
    assert torch_idx < editable_idx
    assert "psycopg[binary]" in log
    assert "prefetch" in log
    assert "[dev]" in log
