"""pg_setup_native.sh のエラーハンドリング・進捗表示テスト。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PG_SETUP_NATIVE = ROOT / "scripts" / "pg_setup_native.sh"


def run_script(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """pg_setup_native.sh を bash で実行して結果を返す。

    env を指定すると現在の環境変数を上書きして実行する。
    """
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)

    return subprocess.run(
        ["bash", str(PG_SETUP_NATIVE), *args],
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


def test_connection_error_keeps_psql_stderr(tmp_path: Path) -> None:
    """接続失敗時に psql の stderr が隠蔽されないこと。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    write_exec(
        bin_dir / "openssl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' 'deadbeefdeadbeefdeadbeefdeadbeef'\n",
    )
    write_exec(
        bin_dir / "psql",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo 'psql: could not connect to server' >&2\n"
        "exit 2\n",
    )

    result = run_script(
        ["--no-install-pgvector", "--skip-schema"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "psql: could not connect to server" in result.stderr
    assert "Cannot connect to PostgreSQL" in result.stderr


def test_non_interactive_without_sudo_fails_with_explicit_message(tmp_path: Path) -> None:
    """非対話かつ sudo 不可の場合に明示エラーで失敗すること。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    write_exec(
        bin_dir / "openssl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' 'deadbeefdeadbeefdeadbeefdeadbeef'\n",
    )
    write_exec(
        bin_dir / "psql",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"$*\" == *\"SELECT 1;\"* ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$*\" == *\"CREATE EXTENSION IF NOT EXISTS vector;\"* ]]; then\n"
        "  echo 'ERROR: extension \"vector\" is not available' >&2\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
    )
    write_exec(
        bin_dir / "sudo",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo 'sudo: a password is required' >&2\n"
        "exit 1\n",
    )

    for cmd in ("apt-get", "yum", "dnf", "brew"):
        write_exec(bin_dir / cmd, "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n")

    result = run_script(
        ["--skip-schema"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "sudo privileges are required" in result.stderr


def test_dnf_best_candidate_retries_with_nobest(tmp_path: Path) -> None:
    """dnf の best candidate エラー時に --nobest 再試行すること。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    dnf_log = tmp_path / "dnf_calls.log"

    write_exec(
        bin_dir / "openssl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' 'deadbeefdeadbeefdeadbeefdeadbeef'\n",
    )
    write_exec(
        bin_dir / "psql",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"$*\" == *\"current_setting('server_version_num')\"* ]]; then\n"
        "  echo '15'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )
    write_exec(
        bin_dir / "sudo",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"$#\" -ge 2 && \"$1\" == \"-n\" && \"$2\" == \"true\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "exec \"$@\"\n",
    )
    write_exec(
        bin_dir / "dnf",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"$*\" >> {dnf_log}\n"
        "if [[ \"$*\" == *\"--nobest\"* ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "echo 'エラー: ジョブの最良アップデート候補をインストールできません' >&2\n"
        "exit 1\n",
    )

    result = run_script(
        ["--no-install-pgvector", "--skip-schema"],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PG_SETUP_DISTRO": "rocky",
        },
    )

    assert result.returncode == 0, result.stderr
    calls = dnf_log.read_text(encoding="utf-8")
    assert "install -y postgresql15-contrib" in calls
    assert "install -y --nobest postgresql15-contrib" in calls


def test_progress_logs_are_printed(tmp_path: Path) -> None:
    """非TTY環境でも段階進捗ログが表示されること。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    write_exec(
        bin_dir / "openssl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' 'deadbeefdeadbeefdeadbeefdeadbeef'\n",
    )
    write_exec(
        bin_dir / "psql",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "exit 0\n",
    )

    result = run_script(
        ["--no-install-pgvector", "--skip-schema"],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PG_SETUP_DISTRO": "macos",
        },
    )

    assert result.returncode == 0
    assert "[1/" in result.stdout
    assert "認証情報を保存" in result.stdout


def test_pgtrgm_available_skips_package_installation(tmp_path: Path) -> None:
    """pg_trgm が既に利用可能なら sudo/パッケージ導入へ進まないこと。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    write_exec(
        bin_dir / "openssl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' 'deadbeefdeadbeefdeadbeefdeadbeef'\n",
    )
    write_exec(
        bin_dir / "psql",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"$*\" == *\"pg_available_extensions\"* && \"$*\" == *\"pg_trgm\"* ]]; then\n"
        "  echo '1'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"$*\" == *\"SELECT 1;\"* ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )
    write_exec(
        bin_dir / "sudo",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo 'sudo should not be called' >&2\n"
        "exit 1\n",
    )

    for cmd in ("apt-get", "yum", "dnf", "brew"):
        write_exec(bin_dir / cmd, "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n")

    result = run_script(
        ["--no-install-pgvector", "--skip-schema"],
        env={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert "pg_trgm is already available" in result.stdout


def test_superuser_password_is_reused_from_env(tmp_path: Path) -> None:
    """管理者パスワードを1回設定すれば全 psql 呼び出しで再利用されること。"""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    pw_log = tmp_path / "pw.log"

    write_exec(
        bin_dir / "openssl",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "printf '%s\\n' 'deadbeefdeadbeefdeadbeefdeadbeef'\n",
    )
    write_exec(
        bin_dir / "psql",
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"echo \"${{PGPASSWORD:-<empty>}}\" >> {pw_log}\n"
        "if [[ \"$*\" == *\"-U postgres\"* ]] && [[ \"${PGPASSWORD:-}\" != \"secret-pass\" ]]; then\n"
        "  echo 'psql: fe_sendauth: no password supplied' >&2\n"
        "  exit 2\n"
        "fi\n"
        "exit 0\n",
    )

    result = run_script(
        ["--no-install-pgvector", "--skip-schema"],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PG_SETUP_DISTRO": "macos",
            "PG_SETUP_POSTGRES_PASSWORD": "secret-pass",
        },
    )

    assert result.returncode == 0, result.stderr
    seen_passwords = [line.strip() for line in pw_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(seen_passwords) >= 3
    assert all(password == "secret-pass" for password in seen_passwords)
