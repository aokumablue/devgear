"""pg_setup.sh の CLI テスト。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PG_SETUP = ROOT / "plugins" / "devgear" / "pg_setup.sh"


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


def make_fake_psql(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "psql.log"
    script = bin_dir / "psql"

    script.write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\n: "${PSQL_LOG:?}"\nprintf "%s\\n" "$@" > "$PSQL_LOG"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)

    return bin_dir, log_path


def make_fake_docker_tools(tmp_path: Path) -> Path:
    """docker17 テスト用の docker と openssl を用意する。"""

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    docker = bin_dir / "docker"
    docker.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ -n "${DOCKER_LOG:-}" ]]; then\n'
        '  printf "%s\\n" "$*" >> "$DOCKER_LOG"\n'
        "fi\n"
        'case "$1" in\n'
        "  compose)\n"
        '    case "${2:-}" in\n'
        "      version|up|down)\n"
        "        exit 0\n"
        "        ;;\n"
        "      *)\n"
        "        exit 1\n"
        "        ;;\n"
        "    esac\n"
        "    ;;\n"
        "  exec)\n"
        '    if [[ "${2:-}" == "-i" ]]; then\n'
        "      shift 2\n"
        '      if [[ "${2:-}" == "psql" ]]; then\n'
        '        if [[ -n "${PSQL_RESET_LOG:-}" && "$*" == *" -d postgres"* ]]; then\n'
        "          cat >\"$PSQL_RESET_LOG\"\n"
        "        else\n"
        "          cat >/dev/null\n"
        "        fi\n"
        "        exit 0\n"
        "      fi\n"
        "      exit 1\n"
        "    fi\n"
        '    if [[ "${3:-}" == "pg_isready" ]]; then\n'
        "      exit 0\n"
        "    fi\n"
        '    if [[ "${3:-}" == "psql" ]]; then\n'
        "      printf 'PostgreSQL 17\\n'\n"
        "      exit 0\n"
        "    fi\n"
        "    exit 1\n"
        "    ;;\n"
        "  *)\n"
        "    exit 1\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    openssl = bin_dir / "openssl"
    openssl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ "${1:-}" == "rand" && "${2:-}" == "-hex" && "${3:-}" == "16" ]]; then\n'
        "  printf '%s\\n' 'deadbeefdeadbeefdeadbeefdeadbeef'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    openssl.chmod(0o755)

    return bin_dir


def test_help_mentions_both_modes() -> None:
    result = run_script(PG_SETUP, ["--help"])

    assert result.returncode == 0, result.stderr
    assert "apply" in result.stdout
    assert "docker17" in result.stdout
    assert ".env" in result.stdout
    assert "lz4 TOAST compression" in result.stdout


def test_apply_mode_uses_mem_pg_url(tmp_path: Path) -> None:
    sql_file = tmp_path / "custom.sql"
    sql_file.write_text("SELECT 1;\n", encoding="utf-8")
    bin_dir, log_path = make_fake_psql(tmp_path)
    postgres_url = "postgresql://user:pass@db.local:5432/devgear_mem"

    result = run_script(
        PG_SETUP,
        ["apply", "--sql-file", str(sql_file)],
        env={
            "MEM_PG_URL": postgres_url,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PSQL_LOG": str(log_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Setup completed successfully!" in result.stdout
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "-v",
        "ON_ERROR_STOP=1",
        postgres_url,
        "-f",
        str(sql_file),
    ]


def test_apply_mode_accepts_positional_url(tmp_path: Path) -> None:
    sql_file = tmp_path / "custom.sql"
    sql_file.write_text("SELECT 1;\n", encoding="utf-8")
    bin_dir, log_path = make_fake_psql(tmp_path)
    postgres_url = "postgresql://user:pass@db.local:5432/devgear_mem"

    result = run_script(
        PG_SETUP,
        [postgres_url, "--sql-file", str(sql_file)],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PSQL_LOG": str(log_path),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Setup completed successfully!" in result.stdout
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        "-v",
        "ON_ERROR_STOP=1",
        postgres_url,
        "-f",
        str(sql_file),
    ]


def test_docker17_mode_creates_env_file_with_random_password(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sql_file = workspace / "pg_setup.sql"
    sql_file.write_text("SELECT 1;\n", encoding="utf-8")
    bin_dir = make_fake_docker_tools(tmp_path)
    home = tmp_path / "home"
    settings_path = home / ".devgear" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    original_settings = json.dumps(
        {
            "project": {
                "git-hosting-service": "github",
            },
            "custom": {
                "keep": True,
            },
        },
        indent=2,
    ) + "\n"
    settings_path.write_text(original_settings, encoding="utf-8")

    result = run_script(
        PG_SETUP,
        [
            "docker17",
            "--workspace",
            str(workspace),
            "--sql-file",
            str(sql_file),
            "--origin-user",
            "alice",
            "--server-host",
            "db.example.com",
        ],
        env={
            "HOME": str(home),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr

    env_file = workspace / ".env"
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "POSTGRES_USER=devgear",
        "POSTGRES_PASSWORD=deadbeefdeadbeefdeadbeefdeadbeef",
        "POSTGRES_DB=devgear_mem",
    ]
    assert env_file.stat().st_mode & 0o777 == 0o600

    compose_file = workspace / "compose.yaml"
    assert "default_toast_compression=lz4" in compose_file.read_text(encoding="utf-8")

    assert settings_path.read_text(encoding="utf-8") == original_settings
    assert "Edit the mem.sync section" in result.stdout
    assert '"interval_hours": 3' in result.stdout
    assert '"origin_user": "alice"' in result.stdout
    assert "Run: python3 -m devgear.mem sync" in result.stdout


def test_docker17_force_resets_existing_database(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sql_file = workspace / "pg_setup.sql"
    sql_file.write_text("SELECT 1;\n", encoding="utf-8")
    env_file = workspace / ".env"
    env_file.write_text(
        "POSTGRES_USER=devgear\n"
        "POSTGRES_PASSWORD=existing-password\n"
        "POSTGRES_DB=devgear_mem\n",
        encoding="utf-8",
    )
    bin_dir = make_fake_docker_tools(tmp_path)
    docker_log = tmp_path / "docker.log"
    reset_log = tmp_path / "reset.sql"

    result = run_script(
        PG_SETUP,
        [
            "docker17",
            "--workspace",
            str(workspace),
            "--sql-file",
            str(sql_file),
            "--origin-user",
            "alice",
            "--server-host",
            "db.example.com",
            "--force",
        ],
        env={
            "DOCKER_LOG": str(docker_log),
            "PSQL_RESET_LOG": str(reset_log),
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 0, result.stderr
    assert env_file.read_text(encoding="utf-8").splitlines() == [
        "POSTGRES_USER=devgear",
        "POSTGRES_PASSWORD=existing-password",
        "POSTGRES_DB=devgear_mem",
    ]

    docker_calls = docker_log.read_text(encoding="utf-8").splitlines()
    assert "compose down -v" in docker_calls
    assert "compose up -d --build" in docker_calls
    assert any("-d postgres" in call for call in docker_calls)
    assert docker_calls.index("compose down -v") < docker_calls.index("compose up -d --build")

    assert reset_log.read_text(encoding="utf-8").splitlines() == [
        "DROP DATABASE IF EXISTS devgear_mem WITH (FORCE);",
        "CREATE DATABASE devgear_mem;",
    ]


def test_dockerfile_template_installs_ca_certificates() -> None:
    content = PG_SETUP.read_text(encoding="utf-8")

    assert "ca-certificates" in content
    assert "docker exec -T" not in content
    assert "ON_ERROR_STOP=1" in content
    assert "default_toast_compression=lz4" in content


def test_pg_setup_sql_uses_unique_index_for_instincts() -> None:
    sql = (ROOT / "plugins" / "devgear" / "pg_setup.sql").read_text(encoding="utf-8")

    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_instincts_unique_key" in sql
    assert "((COALESCE(project_id, '')))" in sql
    assert "ON instincts(origin_user, instinct_id, scope, ((COALESCE(project_id, ''))));" in sql
    assert "last_activated_epoch BIGINT,\n  synced_at TIMESTAMPTZ DEFAULT NOW()\n);" in sql


def test_pg_setup_sql_contains_all_tables() -> None:
    """pg_setup.sql に全テーブルの CREATE TABLE が存在することを確認する。"""
    sql = (ROOT / "plugins" / "devgear" / "pg_setup.sql").read_text(encoding="utf-8")

    required_tables = [
        "memory_chunks",
        "sessions",
        "instincts",
        "adrs",
        "event_logs",
        "interaction_logs",
        "project_profiles",
        "mem_item_runs",
        "memory_chunks_vec",
    ]
    for table in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql or "CREATE TABLE IF NOT EXISTS memory_chunks_vec" in sql, (
            f"{table} の CREATE TABLE が pg_setup.sql に見つかりません"
        )

    # sessions に git メタデータカラムが含まれていること
    assert "branch TEXT" in sql
    assert "commit_hash TEXT" in sql
    assert "uncommitted_count INTEGER" in sql
    assert "ended_at_epoch BIGINT" in sql
    assert "project_profile_id TEXT" in sql

    # interaction_logs に必須カラムが含まれていること
    assert "user_prompt_full TEXT NOT NULL" in sql
    assert "interaction_index INTEGER NOT NULL" in sql
    assert "UNIQUE(origin_user, session_id, interaction_index)" in sql

    # project_profiles に必須カラムが含まれていること
    assert "primary_language TEXT" in sql
    assert "detection_confidence REAL" in sql
    assert "UNIQUE(origin_user, project)" in sql
    assert "origin_host TEXT NOT NULL DEFAULT ''" not in sql

    # mem_item_runs に必須カラムが含まれていること
    assert "skill_name TEXT NOT NULL" in sql
    assert "files_modified_count INTEGER" in sql

    # ベクトル次元が SQLite と一致していること（768次元）
    assert "vector(768)" in sql
    assert "vector(1024)" not in sql
