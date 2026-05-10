"""フックから呼び出される CLI エントリポイント"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from devgear.hooks.hook_common import print_session_start_output as _emit_session_start_output
from devgear.lib.core_utils import get_git_user_name
from devgear.lib.skill_evolution import collect_skill_health, summarize_health_report
from devgear.lib.slim_text import compact_line, first_meaningful_line
from devgear.mem.logger import get as _get_logger
from devgear.mem.settings import Settings

if TYPE_CHECKING:
    from devgear.mem.database import Database, MemoryChunk
    from devgear.mem.search import SearchResult

log = _get_logger("CLI")

# SessionStart フックで JSON 出力が必須なコマンドの集合。
# main() のフォールバック保証とエラー時の早期 return に使用する。
_SESSION_START_COMMANDS: frozenset[str] = frozenset(
    {"setup", "context", "record-project-profile", "team-context"}
)


@contextmanager
def _open_db(settings: Settings):
    from devgear.mem.database import Database

    db = Database(settings.db_path)
    try:
        yield db
    finally:
        db.close()


def embed(texts: list[str], model_name: str) -> list[list[float]]:
    """埋め込み生成を遅延ロードで実行する。"""
    from devgear.mem.embedding import embed as _embed

    return _embed(texts, model_name)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        command = sys.argv[1] if len(sys.argv) >= 2 else ""
        if command in _SESSION_START_COMMANDS:
            _emit_session_start_output()
            sys.exit(0)
        print(HELP_TEXT)
        sys.exit(0)

    command = sys.argv[1]

    try:
        import devgear.mem.logger as _logger_mod

        settings = Settings.load()
        _logger_mod.setup(settings.log_dir, settings.log_level)
    except Exception as e:
        print(f"設定/ログ初期化失敗: {e}", file=sys.stderr)
        if command in _SESSION_START_COMMANDS:
            _emit_session_start_output()
        sys.exit(0)

    stdin_data: dict = {}
    if not sys.stdin.isatty():
        try:
            raw = sys.stdin.read()
            if raw.strip():
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    stdin_data = parsed
        except (json.JSONDecodeError, OSError) as e:
            log.warning("stdin 読み取り失敗: %s", e)

    is_session_start = command in _SESSION_START_COMMANDS
    _session_start_output_done = False

    def _ensure_session_start_output() -> None:
        nonlocal _session_start_output_done
        if is_session_start and not _session_start_output_done:
            _emit_session_start_output()
            _session_start_output_done = True

    try:
        match command:
            case "init":
                _handle_init(settings)
            case "setup":
                _handle_setup(settings)
                _session_start_output_done = True
            case "context":
                _handle_context(settings, stdin_data)
                _session_start_output_done = True
            case "search":
                _handle_search(settings, stdin_data)
            case "session-init":
                _handle_session_init(settings, stdin_data)
            case "observe":
                _handle_observe(settings, stdin_data)
            case "session-end":
                _handle_session_end(settings, stdin_data)
            case "compact":
                _handle_compact(settings)
            case "search-structured":
                _handle_search_structured(settings, stdin_data)
            case "record":
                _handle_record(settings, stdin_data)
            case "sync":
                _handle_sync(settings, stdin_data)
            case "sync-check":
                _handle_sync_check(settings)
            case "import":
                _handle_import(settings, stdin_data)
            case "dashboard":
                _handle_dashboard(settings, stdin_data)
            case "record-interaction":
                _handle_record_interaction(settings, stdin_data)
            case "record-project-profile":
                _handle_record_project_profile(settings, stdin_data)
                _session_start_output_done = True
            case "get-project-profile":
                _handle_get_project_profile(settings, stdin_data)
            case "record-item-run":
                _handle_record_item_run(settings, stdin_data)
            case "team-context":
                _handle_team_context(settings, stdin_data)
                _session_start_output_done = True
            case "team-session-init":
                _handle_team_session_init(settings, stdin_data)
            case _:
                log.error("不明なコマンド: %s", command)
                sys.exit(0)
    except Exception as e:
        log.error("コマンド %s 失敗: %s", command, e)
    finally:
        _ensure_session_start_output()


# --- コマンドハンドラ ---


def _handle_setup(settings: Settings) -> None:
    """Setup: データディレクトリとDB初期化"""
    try:
        _initialize_db(settings)
        log.info("セットアップ完了: %s", settings.data_path)
    except Exception as e:
        log.warning("setup 失敗: %s", e)
    finally:
        _emit_session_start_output()


def _handle_init(settings: Settings) -> None:
    """Init: 既存DBを削除して再作成"""
    _initialize_db(settings, recreate=True)
    log.info("DB再作成完了: %s", settings.db_path)


def _initialize_db(settings: Settings, *, recreate: bool = False) -> None:
    """データディレクトリと mem.db を初期化する。"""
    if recreate:
        _remove_db_artifacts(settings.db_path)

    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.save()
    with _open_db(settings):
        pass


def _remove_db_artifacts(db_path: Path) -> None:
    """SQLite DB と sidecar を削除する。"""
    for path in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
    ):
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def _handle_context(settings: Settings, stdin_data: dict) -> None:
    """SessionStart: コンテキスト注入"""
    from devgear.mem.context import build_context

    project = _get_project(stdin_data)
    ctx = ""
    try:
        with _open_db(settings) as db:
            ctx = build_context(db, settings, project=project)
    except Exception as e:
        log.warning("コンテキスト生成失敗: %s", e)
    finally:
        _emit_session_start_output(ctx)


def _handle_search(settings: Settings, stdin_data: dict) -> None:
    """mem 検索結果を JSON で返す"""
    from devgear.mem.search import SearchService

    query = str(stdin_data.get("query", "") or "")
    if not query.strip():
        print(json.dumps({"results": []}))
        return

    project = stdin_data.get("project") or _get_project(stdin_data)
    limit = _coerce_int(stdin_data.get("limit"), default=20)

    try:
        with _open_db(settings) as db:
            svc = SearchService(db, settings)
            results = svc.search(query=query, project=project, limit=limit)
        print(json.dumps({"results": [r._asdict() for r in results]}))
    except Exception as e:
        log.warning("検索失敗: %s", e)
        print(json.dumps({"results": [], "error": str(e)}))


def _handle_session_init(settings: Settings, stdin_data: dict) -> None:
    """UserPromptSubmit: セッション初期化 + 適応的検索注入"""
    from devgear.mem.database import Session
    from devgear.mem.search import SearchService, should_inject_memory

    session_id = str(stdin_data.get("session_id", "") or "")
    project = _get_project(stdin_data)
    prompt = str(stdin_data.get("prompt", "") or "")

    if project in settings.excluded_projects:
        return

    try:
        with _open_db(settings) as db:
            db.upsert_session(
                Session(
                    session_id=session_id,
                    project=project,
                    started_at_epoch=int(time.time()),
                )
            )

            if not prompt or not should_inject_memory(prompt):
                return

            svc = SearchService(db, settings)
            local_results = svc.search(query=prompt, project=project, limit=3)

            team_results: list[SearchResult] = []
            if settings.sync.enabled and settings.sync.postgres_url:
                git_user = get_git_user_name()
                exclude = git_user if settings.team.exclude_self else None
                try:
                    team_results = svc.search_team(
                        query=prompt,
                        limit=3,
                        exclude_origin_user=exclude,
                    )
                except Exception as e:
                    log.warning("チーム検索失敗（ローカルのみ使用）: %s", e)

            merged = _merge_search_results_rrf(local_results, team_results, top_k=3)

            if merged:
                ctx = _render_adaptive_context(db, merged)
                print(
                    json.dumps(
                        {
                            "hookEventName": "UserPromptSubmit",
                            "additionalContext": ctx,
                        }
                    )
                )
    except Exception as e:
        log.warning("セッション初期化失敗: %s", e)


def _handle_observe(settings: Settings, stdin_data: dict) -> None:
    """PostToolUse: ツール使用をチャンクとして保存"""
    from devgear.mem.chunker import build_chunk_from_tool_use

    session_id = str(stdin_data.get("session_id", "") or "")
    project = _get_project(stdin_data)
    tool_name = str(stdin_data.get("tool_name", "") or "")

    tool_input = stdin_data.get("tool_input")
    tool_response = stdin_data.get("tool_response")
    user_prompt = str(stdin_data.get("prompt", "") or "")

    try:
        with _open_db(settings) as db:
            chunk_index = db.get_next_chunk_index(session_id)
            chunk = build_chunk_from_tool_use(
                session_id=session_id,
                project=project,
                chunk_index=chunk_index,
                user_prompt=user_prompt,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_response=str(tool_response) if tool_response else None,
                chunk_max_length=settings.chunk_max_length,
            )
            db.store_chunk(chunk)
    except Exception as e:
        log.warning("チャンク保存失敗: %s", e)


def _handle_session_end(settings: Settings, stdin_data: dict) -> None:
    """SessionEnd: 埋め込み一括生成 + FTS5 最適化"""
    from devgear.mem.bridge import sync_session_to_observations
    from devgear.mem.compaction import detect_low_quality, find_near_duplicates, optimize_db

    session_id = str(stdin_data.get("session_id", "") or "")

    try:
        with _open_db(settings) as db:
            chunks = db.get_chunks_by_session(session_id)
            if not chunks:
                return

            texts = [c.content for c in chunks]
            embeddings = embed(texts, settings.embedding_model)
            chunk_ids = [c.id for c in chunks if c.id is not None]
            db.store_embeddings(chunk_ids, embeddings)
            log.info("埋め込み保存: session=%s chunks=%d", session_id, len(chunk_ids))

            try:
                db.conn.execute("INSERT INTO memory_chunks_fts(memory_chunks_fts) VALUES('optimize')")
                db.conn.commit()
            except Exception as e:
                log.warning("FTS5 最適化失敗: %s", e)

            try:
                synced = sync_session_to_observations(db, session_id)
                log.info("s-learn 同期: session=%s synced=%d", session_id, synced)
            except Exception as e:
                log.warning("s-learn 同期失敗: %s", e)

            if settings.auto_compact_enabled:
                interval_sec = settings.auto_compact_interval_days * 86400
                if time.time() - settings.last_compacted_at >= interval_sec:
                    try:
                        low_quality_ids = detect_low_quality(db)
                        near_dup_pairs = find_near_duplicates(db)
                        if low_quality_ids:
                            placeholders = ",".join("?" * len(low_quality_ids))
                            db.conn.execute(
                                f"DELETE FROM memory_chunks WHERE id IN ({placeholders})",
                                low_quality_ids,
                            )
                            db.conn.commit()
                        optimize_db(db)
                        settings.last_compacted_at = time.time()
                        settings.save_sync_state()
                        log.info(
                            "自動圧縮完了: 削除=%d 重複ペア=%d",
                            len(low_quality_ids),
                            len(near_dup_pairs),
                        )
                    except Exception as e:
                        log.warning("自動圧縮エラー: %s", e)
    except Exception as e:
        log.warning("セッション終了失敗: %s", e)


def _handle_compact(settings: Settings) -> None:
    """メモリ圧縮コマンド（既定で実行）"""
    from devgear.mem.compaction import detect_low_quality, find_near_duplicates, optimize_db

    try:
        with _open_db(settings) as db:
            low_quality_ids = detect_low_quality(db)
            near_dup_pairs = find_near_duplicates(db)

            print(f"削除候補: {len(low_quality_ids)} 件")
            print(f"重複ペア: {len(near_dup_pairs)} 件")

            if low_quality_ids:
                placeholders = ",".join("?" * len(low_quality_ids))
                db.conn.execute(
                    f"DELETE FROM memory_chunks WHERE id IN ({placeholders})",
                    low_quality_ids,
                )
                db.conn.commit()
            opt = optimize_db(db)
            print(f"実行済み（断片化率: {opt.get('fragmentation_before', 0):.1%}）")
    except Exception as e:
        print("DB に接続できません", file=sys.stderr)
        log.warning("圧縮失敗: %s", e)


def _handle_search_structured(settings: Settings, stdin_data: dict) -> None:
    """構造化検索: tool_name, files, date_range フィルタをサポート"""
    from devgear.mem.search import SearchService

    query = str(stdin_data.get("query", "") or "")
    project = stdin_data.get("project") or _get_project(stdin_data)
    limit = _coerce_int(stdin_data.get("limit"), default=20)
    tool_filter = stdin_data.get("tool_name")
    file_pattern = stdin_data.get("file_pattern")
    date_from = stdin_data.get("date_from")
    date_to = stdin_data.get("date_to")

    try:
        with _open_db(settings) as db:
            if query.strip():
                svc = SearchService(db, settings)
                candidate_ids = [r.chunk_id for r in svc.search(query=query, project=project, limit=limit * 3)]
            else:
                candidate_ids = [c.id for c in db.get_recent_chunks(limit=limit * 3, project=project) if c.id is not None]

            filtered = _apply_structured_filters(db, candidate_ids, tool_filter, file_pattern, date_from, date_to)

            results = []
            for chunk_id in filtered[:limit]:
                chunk = db.get_chunk_by_id(chunk_id)
                if chunk:
                    results.append(
                        {
                            "chunk_id": chunk_id,
                            "content": chunk.content,
                            "user_prompt": chunk.user_prompt,
                            "project": chunk.project,
                            "created_at_epoch": chunk.created_at_epoch,
                            "tool_names": chunk.tool_names,
                            "files_read": chunk.files_read,
                            "files_modified": chunk.files_modified,
                        }
                    )

        print(json.dumps({"results": results, "total": len(results)}))
    except Exception as e:
        log.warning("構造化検索失敗: %s", e)
        print(json.dumps({"results": [], "error": str(e)}))


def _apply_structured_filters(
    db: Database,
    candidate_ids: list[int],
    tool_filter: str | None,
    file_pattern: str | None,
    date_from: int | str | None,
    date_to: int | str | None,
) -> list[int]:
    """候補チャンクに構造化フィルタを適用"""
    import fnmatch

    if not candidate_ids:
        return []

    chunks = db.get_chunks_by_ids(candidate_ids)
    from_epoch = _parse_date_to_epoch(date_from) if date_from else None
    to_epoch = _parse_date_to_epoch(date_to) if date_to else None
    filtered = []

    for chunk_id in candidate_ids:
        chunk = chunks.get(chunk_id)
        if not chunk:
            continue
        if tool_filter and tool_filter not in chunk.tool_names:
            continue
        if file_pattern:
            all_files = chunk.files_read + chunk.files_modified
            if not any(fnmatch.fnmatch(f, file_pattern) for f in all_files):
                continue
        if from_epoch and chunk.created_at_epoch < from_epoch:
            continue
        if to_epoch and chunk.created_at_epoch > to_epoch:
            continue
        filtered.append(chunk_id)

    return filtered


def _parse_date_to_epoch(value: int | str | None) -> int | None:
    """日付（epoch または ISO 8601）をエポックに変換"""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        return None


def _handle_record(settings: Settings, stdin_data: dict) -> None:
    """明示的記録: コマンド/スキル/エージェントからの直接記録"""
    from devgear.mem.database import MemoryChunk, Session

    session_id = str(stdin_data.get("session_id", "") or f"record-{int(time.time())}")
    project = _get_project(stdin_data)
    event_type = str(stdin_data.get("event_type", "custom") or "custom")
    content = str(stdin_data.get("content", "") or "")
    user_prompt = str(stdin_data.get("user_prompt", "") or "")
    metadata = stdin_data.get("metadata", {})

    if not content.strip():
        print(json.dumps({"success": False, "error": "content is required"}))
        return

    try:
        with _open_db(settings) as db:
            db.upsert_session(
                Session(
                    session_id=session_id,
                    project=project,
                    started_at_epoch=int(time.time()),
                )
            )

            chunk_index = db.get_next_chunk_index(session_id)
            files_read = metadata.get("files_read", [])
            files_modified = metadata.get("files_modified", [])

            chunk = MemoryChunk(
                session_id=session_id,
                project=project,
                chunk_index=chunk_index,
                content=content,
                tool_names=[event_type],
                files_read=files_read if isinstance(files_read, list) else [],
                files_modified=files_modified if isinstance(files_modified, list) else [],
                user_prompt=user_prompt,
                created_at_epoch=int(time.time()),
            )
            chunk_id = db.store_chunk(chunk)

        print(json.dumps({"success": True, "chunk_id": chunk_id}))
    except Exception as e:
        log.warning("記録失敗: %s", e)
        print(json.dumps({"success": False, "error": str(e)}))


def _get_project(stdin_data: dict) -> str:
    """cwd からプロジェクト名を導出する"""
    cwd = stdin_data.get("cwd", os.getcwd())
    return os.path.basename(cwd)


def _coerce_int(value: object, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _merge_search_results_rrf(
    local_results: list[SearchResult],
    team_results: list[SearchResult],
    top_k: int = 3,
    k: int = 60,
) -> list[SearchResult]:
    """ローカルとチームの検索結果を RRF で統合して上位 top_k 件を返す。

    team_results が空の場合は local_results の先頭 top_k 件を返す。
    team の chunk_id は "team:" プレフィックスで衝突を防ぐ。
    """
    if not team_results:
        return local_results[:top_k]

    scores: dict[str, float] = {}
    result_map: dict[str, SearchResult] = {}

    for rank, result in enumerate(local_results):
        key = str(result.chunk_id)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        result_map[key] = result

    for rank, result in enumerate(team_results):
        key = f"team:{result.chunk_id}"
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        result_map[key] = result

    sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)
    return [result_map[kk] for kk in sorted_keys[:top_k]]


def _render_adaptive_context(db: Database, results: list[SearchResult], max_tokens: int = 400) -> str:
    """検索結果を <mem-context> タグでラップした Markdown 文字列を生成する。

    team 検索結果（DB に存在しない chunk_id）は SearchResult から直接フォーマットする。
    max_tokens を超えた時点でチャンクの追加を打ち切る（1 トークン ≈ 3.5 文字で換算）。
    各チャンクは prompt/本文を slim_text で圧縮し、フェンス付きコードブロックは保持する。
    """
    lines = ["<mem-context>", "# 関連メモリ（適応的注入）", ""]
    current_session = ""
    budget = max_tokens * 3.5

    for result in results:
        chunk = db.get_chunk_by_id(result.chunk_id)
        if chunk:
            if chunk.session_id != current_session:
                current_session = chunk.session_id
                ts = _format_timestamp(chunk.created_at_epoch)
                lines.append(f"## {chunk.project} ({ts})")
                lines.append("")
            chunk_str = _format_chunk(chunk)
        else:
            # team 検索結果は SQLite に存在しないため SearchResult から生成
            chunk_str = _format_chunk_from_result(result)

        if budget - len(chunk_str) < 0:
            break
        lines.append(chunk_str)
        budget -= len(chunk_str)

    lines.append("</mem-context>")
    return "\n".join(lines)


def _format_fields(
    user_prompt: str,
    tool_names: list[str],
    files_modified: list[str],
    content: str,
) -> str:
    """プロンプト・ツール・変更ファイル・本文を Markdown 形式にフォーマットする。"""
    parts: list[str] = []
    if user_prompt:
        parts.append(f"**プロンプト**: {_slim_prompt(user_prompt)}")
    if tool_names:
        parts.append(f"**ツール**: {', '.join(tool_names)}")
    if files_modified:
        parts.append(f"**変更ファイル**: {', '.join(files_modified[:5])}")
    if content:
        parts.append(_slim_context_content(content))
    parts.append("")
    return "\n".join(parts)


def _format_chunk_from_result(result: SearchResult) -> str:
    """SearchResult をチャンクフォーマットに変換する（team 検索結果用）。"""
    return _format_fields(result.user_prompt, result.tool_names, result.files_modified, result.content)


def _format_chunk(chunk: MemoryChunk) -> str:
    """MemoryChunk をチャンクフォーマットに変換する。"""
    return _format_fields(chunk.user_prompt, chunk.tool_names, chunk.files_modified, chunk.content)


def _format_timestamp(epoch: int) -> str:
    dt = datetime.fromtimestamp(epoch, tz=UTC)
    return dt.strftime("%Y-%m-%d %H:%M")


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _slim_prompt(text: str, max_len: int = 160) -> str:
    """会話調の前置きを落として、プロンプトを短く直接的に整える。

    通常行から意味のある先頭行を抽出し、コードブロック内のみのテキストには
    コードブロックの最初の非空行を使用する。
    """
    line = first_meaningful_line(text)
    if line:
        return compact_line(line, max_len)

    # コードブロック内の先頭行をフォールバックとして使う
    in_code_block = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block and stripped:
            return compact_line(stripped, max_len)

    return ""


def _slim_context_content(text: str, *, max_prose_lines: int = 6, max_prose_line_length: int = 160) -> str:
    """本文を圧縮しつつ、フェンス付きコードブロックはそのまま残す。"""
    if not text:
        return ""

    lines: list[str] = []
    in_code_block = False
    prose_lines = 0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            lines.append(stripped)
            continue

        if in_code_block:
            lines.append(line)
            continue

        if prose_lines >= max_prose_lines:
            if lines and lines[-1] != "...":
                lines.append("...")
            continue

        compacted = compact_line(line, max_prose_line_length)
        if compacted:
            lines.append(compacted)
            prose_lines += 1

    return "\n".join(lines)


def _handle_sync(settings: Settings, stdin_data: dict) -> None:
    """PostgreSQL への同期を実行する。

    stdin_data:
      dry_run: bool - True の場合、実際の同期は行わない
    """
    from devgear.mem.sync import sync_to_postgres

    dry_run = stdin_data.get("dry_run", False)
    result = sync_to_postgres(settings, dry_run=dry_run)

    output = {
        "success": result.success,
        "error": result.error,
        "synced": {
            "chunks": result.chunks,
            "sessions": result.sessions,
            "instincts": result.instincts,
            "adrs": result.adrs,
            "events": result.events,
        },
    }
    print(json.dumps(output, ensure_ascii=False))


def _handle_sync_check(settings: Settings) -> None:
    """同期間隔をチェックし、必要なら同期を実行する。"""
    from devgear.mem.sync import should_sync, sync_to_postgres

    if not should_sync(settings):
        log.debug("sync-check: スキップ")
        return

    log.info("sync-check: 同期実行")
    result = sync_to_postgres(settings)

    if not result.success:
        log.warning("sync-check: 同期失敗 - %s", result.error)


def _count_lines(path: Path) -> int:
    """ファイルの行数を数える。"""
    try:
        if not path.exists():
            return 0
        with path.open(encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _collect_project_overview() -> dict:
    """既知プロジェクトと instinct の集計を返す。"""
    from devgear.skills.learn.cli import (
        GLOBAL_INHERITED_DIR,
        GLOBAL_PERSONAL_DIR,
        _load_instincts_from_dir,
        _project_dir_for_id,
        load_registry,
    )

    registry = load_registry()
    projects: list[dict[str, object]] = []
    total_personal = 0
    total_inherited = 0

    valid_projects = [(pid, info) for pid, info in registry.items() if isinstance(info, dict)]
    if len(valid_projects) != len(registry):
        log.warning("project registry contains invalid entries; skipping them")

    for project_id, project_info in sorted(
        valid_projects,
        key=lambda item: str(item[1].get("last_seen", "")),
        reverse=True,
    ):
        project_dir = _project_dir_for_id(project_id)
        personal_count = len(_load_instincts_from_dir(project_dir / "instincts" / "personal", "personal", "project"))
        inherited_count = len(_load_instincts_from_dir(project_dir / "instincts" / "inherited", "inherited", "project"))
        total_personal += personal_count
        total_inherited += inherited_count
        projects.append(
            {
                "id": project_id,
                "name": project_info.get("name", project_id),
                "personal_instincts": personal_count,
                "inherited_instincts": inherited_count,
                "observations": _count_lines(project_dir / "observations.jsonl"),
                "last_seen": project_info.get("last_seen", "unknown"),
            }
        )

    global_personal = len(_load_instincts_from_dir(GLOBAL_PERSONAL_DIR, "personal", "global"))
    global_inherited = len(_load_instincts_from_dir(GLOBAL_INHERITED_DIR, "inherited", "global"))

    return {
        "projects": projects,
        "summary": {
            "total_projects": len(valid_projects),
            "personal_instincts": total_personal,
            "inherited_instincts": total_inherited,
            "global_personal": global_personal,
            "global_inherited": global_inherited,
        },
    }


def _collect_skill_health_overview(options: dict[str, object]) -> dict[str, object]:
    """skill health の集計データを返す。"""
    try:
        report = collect_skill_health(options)
    except Exception as error:  # noqa: BLE001 - ダッシュボードは失敗で止めない
        log.warning("skill health collection failed: %s", error)
        report = {"generated_at": None, "skills": []}

    summary = summarize_health_report(report)
    skills = sorted(
        report.get("skills", []),
        key=lambda skill: (
            not bool(skill.get("declining")),
            -int(skill.get("run_count_30d", 0) or 0),
            str(skill.get("skill_id", "")),
        ),
    )
    display_skills = skills[:20]

    return {
        "report": report,
        "summary": summary,
        "skills": display_skills,
        "chart_labels": [str(skill.get("skill_id", "")) for skill in display_skills],
        "chart_7d": [
            round(float(skill.get("success_rate_7d") or 0) * 100, 1) if skill.get("success_rate_7d") is not None else 0
            for skill in display_skills
        ],
        "chart_30d": [
            round(float(skill.get("success_rate_30d") or 0) * 100, 1) if skill.get("success_rate_30d") is not None else 0
            for skill in display_skills
        ],
    }


def _collect_skill_growth_overview(settings: Settings, days: int) -> dict[str, object]:
    """skill growth の提案データを返す。"""
    sync_cfg = settings.sync
    empty = {
        "summary": {"total_patterns": 0, "total_gaps": 0, "skill_candidates": 0, "gap_candidates": 0},
        "skill_candidates": [],
        "gap_candidates": [],
        "action_items": [],
        "chart_labels": [],
        "chart_scores": [],
    }

    if not sync_cfg.enabled or not sync_cfg.postgres_url:
        return empty

    try:
        from devgear.mem import skill_analyzer, skill_proposal
        from devgear.mem.pg_database import PgDatabase

        pg = PgDatabase(sync_cfg.postgres_url)
        if not pg.test_connection():
            return empty

        try:
            patterns = skill_analyzer.detect_repeated_patterns(pg, min_count=3, days=days)
            gaps = skill_analyzer.detect_skill_gaps(pg, days=days)
            proposal = skill_proposal.generate_proposal(patterns, gaps)
        finally:
            pg.close()
    except Exception as error:  # noqa: BLE001 - ダッシュボードは失敗で止めない
        log.warning("skill growth collection failed: %s", error)
        return empty

    skill_candidates = list(proposal.get("skill_candidates", []))[:10]
    gap_candidates = list(proposal.get("gap_candidates", []))[:10]
    action_items = list(proposal.get("action_items", []))[:10]

    return {
        "summary": proposal.get("summary", empty["summary"]),
        "skill_candidates": skill_candidates,
        "gap_candidates": gap_candidates,
        "action_items": action_items,
        "chart_labels": [str(item.get("suggested_name", "")) for item in skill_candidates],
        "chart_scores": [int(item.get("priority_score", 0) or 0) for item in skill_candidates],
    }


def _handle_import(settings: Settings, stdin_data: dict) -> None:
    """外部データを mem に取り込む。

    stdin_data:
      types: list[str] - 取り込み対象（"instincts", "adrs", "events"）
      repo_root: str - リポジトリルート（ADR 用）
    """
    from devgear.mem.importers import import_adrs, import_event_logs, import_instincts

    origin_user = get_git_user_name()
    types = stdin_data.get("types", ["instincts", "adrs", "events"])
    repo_root = stdin_data.get("repo_root")

    result = {"instincts": 0, "adrs": 0, "events": 0}

    with _open_db(settings) as db:
        if "instincts" in types:
            result["instincts"] = import_instincts(db, origin_user)

        if "adrs" in types and repo_root:
            result["adrs"] = import_adrs(db, origin_user, repo_root)

        if "events" in types:
            result["events"] = import_event_logs(db, origin_user)

    print(json.dumps({"success": True, "imported": result}, ensure_ascii=False))


def _handle_dashboard(settings: Settings, stdin_data: dict) -> None:
    """静的 HTML ダッシュボードを生成する。

    個人データ（SQLite）を常に収集し、PostgreSQL が設定されている場合はチームデータも収集して
    1 つのグラフ内で個人 vs チームを比較表示する。

    stdin_data:
      output: str - 出力ファイルパス（デフォルト: /tmp/devgear-dashboard.html）
      days: int - 集計期間（デフォルト: 30）
      format: str - "html" or "json"（デフォルト: html）
    """
    import re
    from datetime import datetime
    from pathlib import Path

    from devgear.mem import dashboard_queries as dq
    from devgear.mem import item_usage_queries as iq
    from devgear.mem.item_usage_queries import _PG_PLACEHOLDER, _SQLITE_PLACEHOLDER

    def _jdumps(obj: object) -> str:
        """HTML <script> ブロック埋め込み用 JSON。</script> タグのブレークを防ぐ。"""
        return re.sub(r"</", r"<\\/", json.dumps(obj, ensure_ascii=False))

    days = stdin_data.get("days", 30)
    output_path = stdin_data.get("output", "/tmp/devgear-dashboard.html")
    output_format = stdin_data.get("format", "html")

    with _open_db(settings) as db:
        sqlite_conn = db.conn
        personal_ranking = iq.item_usage_ranking(sqlite_conn, _SQLITE_PLACEHOLDER, days)
        personal_trend = iq.daily_trend(sqlite_conn, _SQLITE_PLACEHOLDER, days)
        personal_outcome = iq.outcome_distribution(sqlite_conn, _SQLITE_PLACEHOLDER, days)

    pg_available = False
    team_ranking: list = []
    team_trend: list = []
    pg_data: dict = {
        "user_activity": [], "project_activity": [], "tool_usage": [],
        "timeline": [], "instinct_growth": [],
        "quality": {"total_chunks": 0, "total_users": 0, "total_projects": 0,
                    "total_sessions": 0, "access_rate": 0, "short_chunk_rate": 0},
        "file_heatmap": [],
    }

    sync_cfg = settings.sync
    if sync_cfg.enabled and sync_cfg.postgres_url:
        try:
            from devgear.mem.pg_database import PgDatabase
            pg = PgDatabase(sync_cfg.postgres_url)
            if pg.test_connection():
                try:
                    pg_conn = pg._get_conn()
                    try:
                        team_ranking = iq.item_usage_ranking(pg_conn, _PG_PLACEHOLDER, days)
                        team_trend = iq.daily_trend(pg_conn, _PG_PLACEHOLDER, days)
                        pg_available = True
                    finally:
                        pg._put_conn(pg_conn)
                    pg_data = {
                        "user_activity": dq.activity_by_user(pg, days),
                        "project_activity": dq.activity_by_project(pg, days),
                        "tool_usage": dq.tool_usage_distribution(pg, days),
                        "timeline": dq.session_timeline(pg, days),
                        "instinct_growth": dq.instinct_growth(pg),
                        "quality": dq.memory_quality_metrics(pg),
                        "file_heatmap": dq.file_change_heatmap(pg, days),
                    }
                except Exception as e:
                    log.warning("既存パネルデータ取得失敗: %s", e)
                finally:
                    pg.close()
        except Exception as e:
            log.warning("PostgreSQL 接続失敗（個人データのみ表示）: %s", e)

    skill_labels, skill_personal = iq.make_ranking_data(personal_ranking, "skill")
    skill_team = iq.align_team_counts(skill_labels, team_ranking, "skill")

    cmd_labels, cmd_personal = iq.make_ranking_data(personal_ranking, "command")
    cmd_team = iq.align_team_counts(cmd_labels, team_ranking, "command")

    agent_labels, agent_personal = iq.make_ranking_data(personal_ranking, "agent")
    agent_team = iq.align_team_counts(agent_labels, team_ranking, "agent")

    personal_trend_by_date = {r["date"]: r["total"] for r in personal_trend}
    team_trend_by_date = {r["date"]: r["total"] for r in team_trend}
    all_dates = sorted(set(list(personal_trend_by_date.keys()) + list(team_trend_by_date.keys())))
    trend_personal_vals = [personal_trend_by_date.get(d, 0) for d in all_dates]
    trend_team_vals = [team_trend_by_date.get(d, 0) for d in all_dates]

    item_has_data = bool(personal_ranking)
    skill_health = _collect_skill_health_overview(dict(stdin_data))
    skill_growth = _collect_skill_growth_overview(settings, int(days))
    project_overview = _collect_project_overview()

    data = {
        **pg_data,
        "personal_ranking": personal_ranking,
        "team_ranking": team_ranking,
        "personal_outcome": personal_outcome,
        "skill_health": skill_health,
        "skill_growth": skill_growth,
        "project_overview": project_overview,
    }

    if output_format == "json":
        Path(output_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"success": True, "output": output_path}))
        return

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html")

    html = template.render(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        days=days,
        quality=pg_data["quality"],
        user_labels=_jdumps([d["user"] for d in pg_data["user_activity"]]),
        user_data=_jdumps([d["chunks"] for d in pg_data["user_activity"]]),
        project_labels=_jdumps([d["project"] for d in pg_data["project_activity"]]),
        project_data=_jdumps([d["chunks"] for d in pg_data["project_activity"]]),
        tool_labels=_jdumps([d["tool"] for d in pg_data["tool_usage"]]),
        tool_data=_jdumps([d["count"] for d in pg_data["tool_usage"]]),
        timeline_dates=_jdumps([d["date"] for d in pg_data["timeline"]]),
        timeline_sessions=_jdumps([d["sessions"] for d in pg_data["timeline"]]),
        timeline_chunks=_jdumps([d["chunks"] for d in pg_data["timeline"]]),
        instinct_dates=_jdumps([d["date"] for d in pg_data["instinct_growth"]]),
        instinct_counts=_jdumps([d["count"] for d in pg_data["instinct_growth"]]),
        file_heatmap=pg_data["file_heatmap"],
        # アイテム使用率パネル
        pg_available=pg_available,
        item_has_data=item_has_data,
        item_skill_labels=_jdumps(skill_labels),
        item_skill_personal=_jdumps(skill_personal),
        item_skill_team=_jdumps(skill_team),
        item_command_labels=_jdumps(cmd_labels),
        item_command_personal=_jdumps(cmd_personal),
        item_command_team=_jdumps(cmd_team),
        item_agent_labels=_jdumps(agent_labels),
        item_agent_personal=_jdumps(agent_personal),
        item_agent_team=_jdumps(agent_team),
        item_trend_dates=_jdumps(all_dates),
        item_trend_personal=_jdumps(trend_personal_vals),
        item_trend_team=_jdumps(trend_team_vals),
        item_outcome_labels=_jdumps([d["outcome"] for d in personal_outcome]),
        item_outcome_personal=_jdumps([d["count"] for d in personal_outcome]),
        skill_health_summary=skill_health["summary"],
        skill_health_labels=_jdumps(skill_health["chart_labels"]),
        skill_health_7d=_jdumps(skill_health["chart_7d"]),
        skill_health_30d=_jdumps(skill_health["chart_30d"]),
        skill_health_rows=skill_health["skills"],
        skill_growth_summary=skill_growth["summary"],
        skill_growth_labels=_jdumps(skill_growth["chart_labels"]),
        skill_growth_scores=_jdumps(skill_growth["chart_scores"]),
        skill_candidates=skill_growth["skill_candidates"],
        gap_candidates=skill_growth["gap_candidates"],
        action_items=skill_growth["action_items"],
        project_summary=project_overview["summary"],
        project_rows=project_overview["projects"],
    )

    Path(output_path).write_text(html, encoding="utf-8")
    print(json.dumps({"success": True, "output": output_path}))


def _handle_record_interaction(settings: Settings, stdin_data: dict) -> None:
    """interaction_logs へのインタラクション記録。

    stdin_data:
      session_id: str
      user_prompt_full: str - ユーザー指示の全文
      ai_response_summary: str - AI 応答の要約（オプション）
      ai_response_tool_plan: str - AI 応答内のツール使用計画 JSON（オプション）
      chunk_id: str - 対応チャンク ID（オプション）
      execution_outcome: str - 'success'|'partial'|'failure'|'unknown'
      tool_error_count: int
    """
    from devgear.mem.database import InteractionLog, Session

    session_id = str(stdin_data.get("session_id", "") or "")
    project = _get_project(stdin_data)
    user_prompt_full = str(stdin_data.get("user_prompt_full", "") or "")

    if not user_prompt_full.strip():
        print(json.dumps({"success": False, "error": "user_prompt_full is required"}))
        return

    try:
        with _open_db(settings) as db:
            db.upsert_session(
                Session(
                    session_id=session_id,
                    project=project,
                    started_at_epoch=int(time.time()),
                )
            )
            interaction_index = db.get_next_interaction_index(session_id)
            log_entry = InteractionLog(
                session_id=session_id,
                project=project,
                user_prompt_full=user_prompt_full,
                interaction_index=interaction_index,
                created_at_epoch=int(time.time()),
                origin_user=get_git_user_name(),
                ai_response_summary=str(stdin_data.get("ai_response_summary", "") or "") or None,
                ai_response_tool_plan=str(stdin_data.get("ai_response_tool_plan", "") or "") or None,
                chunk_id=str(stdin_data.get("chunk_id", "") or "") or None,
                execution_outcome=str(stdin_data.get("execution_outcome", "unknown") or "unknown"),
                tool_error_count=int(stdin_data.get("tool_error_count", 0) or 0),
            )
            log_id = db.store_interaction_log(log_entry)
        print(json.dumps({"success": True, "id": log_id, "interaction_index": interaction_index}))
    except Exception as e:
        log.warning("インタラクション記録失敗: %s", e)
        print(json.dumps({"success": False, "error": str(e)}))


def _handle_record_project_profile(settings: Settings, stdin_data: dict) -> None:
    """project_profiles のアップサート。

    stdin_data:
      project: str
      project_path: str
      languages: list[str]
      frameworks: list[str]
      primary_language: str
      test_command: str
      build_command: str
      scope_hint: str - 'global'|'project'
    """
    from devgear.mem.database import ProjectProfile

    project = stdin_data.get("project") or _get_project(stdin_data)
    now = int(time.time())

    try:
        with _open_db(settings) as db:
            profile = ProjectProfile(
                project=project,
                detected_at_epoch=now,
                last_updated_epoch=now,
                origin_user=get_git_user_name(),
                project_path=str(stdin_data.get("project_path", "") or "") or None,
                languages=stdin_data.get("languages", []) or [],
                frameworks=stdin_data.get("frameworks", []) or [],
                primary_language=str(stdin_data.get("primary_language", "") or "") or None,
                test_command=str(stdin_data.get("test_command", "") or "") or None,
                build_command=str(stdin_data.get("build_command", "") or "") or None,
                scope_hint=str(stdin_data.get("scope_hint", "project") or "project"),
            )
            profile_id = db.upsert_project_profile(profile)
        log.info("project profile saved: %s (id=%s)", project, profile_id)
    except Exception as e:
        log.warning("プロジェクトプロファイル保存失敗: %s", e)
    finally:
        _emit_session_start_output()


def _handle_get_project_profile(settings: Settings, stdin_data: dict) -> None:
    """project_profiles の取得。

    stdin_data:
      project: str
    """
    project = stdin_data.get("project") or _get_project(stdin_data)

    try:
        with _open_db(settings) as db:
            profile = db.get_project_profile(project, origin_user=get_git_user_name())
        if profile:
            print(
                json.dumps(
                    {
                        "found": True,
                        "project": profile.project,
                        "languages": profile.languages,
                        "frameworks": profile.frameworks,
                        "primary_language": profile.primary_language,
                        "scope_hint": profile.scope_hint,
                        "last_updated_epoch": profile.last_updated_epoch,
                    },
                    ensure_ascii=False,
                )
            )
        else:
            print(json.dumps({"found": False}))
    except Exception as e:
        log.warning("プロジェクトプロファイル取得失敗: %s", e)
        print(json.dumps({"found": False, "error": str(e)}))


def _handle_record_item_run(settings: Settings, stdin_data: dict) -> None:
    """スキル・コマンド・エージェントの実行記録を mem_item_runs に保存する。

    PostToolUse(Skill) フックから渡される stdin 形式:
      tool_name: "Skill"
      tool_input: {"skill": "<skill-name>", ...}

    または直接呼び出し時:
      item_type: str  - "skill" | "command" | "agent"（デフォルト: "skill"）
      skill_name: str - スキル/コマンド/エージェント名（必須）
      session_id: str - セッションID
      project: str    - プロジェクト名
      outcome: str    - "success" | "partial" | "failure" | "unknown"（デフォルト: "unknown"）
      skill_trigger: str | None  - トリガープロンプト先頭200文字
      duration_seconds: int | None
    """
    from devgear.mem.database import MemItemRun

    tool_input = stdin_data.get("tool_input", {})
    if isinstance(tool_input, dict) and tool_input.get("skill"):
        skill_name = str(tool_input["skill"])
        item_type = "skill"
    else:
        skill_name = str(stdin_data.get("skill_name", "") or "")
        item_type = stdin_data.get("item_type", "skill")

    if not skill_name:
        log.warning("record-item-run: skill_name が未指定")
        return

    if item_type not in ("skill", "command", "agent"):
        log.warning("record-item-run: 不正な item_type=%s", item_type)
        return

    session_id = str(stdin_data.get("session_id", "") or "")
    project = _get_project(stdin_data)
    created_at_epoch = int(time.time())

    run = MemItemRun(
        session_id=session_id,
        project=project,
        skill_name=skill_name,
        created_at_epoch=created_at_epoch,
        origin_user=get_git_user_name(),
        item_type=item_type,
        outcome=stdin_data.get("outcome", "unknown"),
        skill_trigger=stdin_data.get("skill_trigger"),
        duration_seconds=stdin_data.get("duration_seconds"),
    )

    try:
        with _open_db(settings) as db:
            run_id = db.store_mem_item_run(run)
        log.info("item_run 記録: %s (%s) id=%s", skill_name, item_type, run_id)
        print(json.dumps({"success": True, "id": run_id}))
    except Exception as e:
        log.warning("record-item-run 失敗: %s", e)
        print(json.dumps({"success": False, "error": str(e)}))


def _handle_team_context(settings: Settings, stdin_data: dict) -> None:
    """SessionStart: PostgreSQL チーム共有チャンクから ``<team-context>`` を注入。

    FTS のみの軽量クエリで、起動時のレイテンシを最小化する。接続失敗やデータ不在時は
    静かにスキップするが、SessionStart の出力契約は満たす。
    """
    sync_cfg = settings.sync
    ctx = ""
    if not settings.team.enabled or not sync_cfg.enabled or not sync_cfg.postgres_url:
        _emit_session_start_output()
        return

    project = _get_project(stdin_data)
    if not project:
        _emit_session_start_output()
        return
    if project in settings.excluded_projects:
        _emit_session_start_output()
        return

    git_user = get_git_user_name()

    try:
        from devgear.mem.pg_database import PgDatabase
        from devgear.mem.team_context import build_team_context
    except Exception as e:
        log.warning("team-context モジュール読み込み失敗: %s", e)
        _emit_session_start_output()
        return

    pg = None
    try:
        pg = PgDatabase(sync_cfg.postgres_url)
        if not pg.test_connection():
            log.warning("team-context: PostgreSQL 接続失敗")
            return
        exclude = git_user if settings.team.exclude_self else ""
        ctx = build_team_context(
            pg,
            query=project,
            exclude_origin_user=exclude,
            settings=settings.team,
            mode="fts",
        )
    except Exception as e:
        log.warning("team-context 生成失敗: %s", e)
    finally:
        if pg is not None:
            pg.close()
        _emit_session_start_output(ctx)


def _handle_team_session_init(settings: Settings, stdin_data: dict) -> None:
    """UserPromptSubmit: 過去参照プロンプト検出時にチーム横断ベクトル検索を実行する。

    ``should_inject_memory`` ゲートで発火頻度を抑制し、埋め込みモデルのロードは
    実際に必要になった瞬間だけ発生させる。PG 未設定・接続失敗・空結果時は何も出力しない。
    """
    from devgear.mem.search import should_inject_memory

    sync_cfg = settings.sync
    if not settings.team.enabled or not sync_cfg.enabled or not sync_cfg.postgres_url:
        return

    prompt = str(stdin_data.get("prompt", "") or "")
    if not prompt or not should_inject_memory(prompt):
        return

    project = _get_project(stdin_data)
    if project in settings.excluded_projects:
        return

    git_user = get_git_user_name()
    query = f"{project} {prompt}".strip() if project else prompt

    try:
        from devgear.mem.pg_database import PgDatabase
        from devgear.mem.team_context import build_team_context
    except Exception as e:
        log.warning("team-session-init モジュール読み込み失敗: %s", e)
        return

    pg = PgDatabase(sync_cfg.postgres_url)
    try:
        if not pg.test_connection():
            log.warning("team-session-init: PostgreSQL 接続失敗")
            return
        exclude = git_user if settings.team.exclude_self else ""
        ctx = build_team_context(
            pg,
            query=query,
            exclude_origin_user=exclude,
            settings=settings.team,
            mode="hybrid",
            embedding_model=settings.embedding_model,
        )
        if ctx:
            print(
                json.dumps(
                    {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": ctx,
                    }
                )
            )
    except Exception as e:
        log.warning("team-session-init 生成失敗: %s", e)
    finally:
        pg.close()


HELP_TEXT = """\
CLI Commands for mem

Usage:
  python -m devgear.mem <command>

Commands:
  init               Recreate the local mem database from scratch
  setup              Initialize the local mem database
  context            Build <mem-context> from the local database (reads JSON from stdin)
  search             Search the local database (reads JSON from stdin)
  search-structured  Structured search with filters (tool_name, file_pattern, date_range)
  record             Explicitly record an event from commands/skills/agents
  session-init       Initialize a session and inject adaptive memory (reads JSON from stdin)
  observe            Store a tool-use chunk (reads JSON from stdin)
  session-end        Embed and compact the current session (reads JSON from stdin)
  compact            Execute memory compaction
  sync               Sync local SQLite data to PostgreSQL (reads JSON from stdin)
  sync-check         Check sync interval and sync if needed
  import             Import external data (instincts, adrs, events) to mem
  dashboard          Generate a static HTML dashboard from PostgreSQL data
  record-interaction     Record a user/AI interaction pair to interaction_logs
  record-project-profile Upsert project tech stack to project_profiles
  get-project-profile    Get project tech stack from project_profiles
  record-item-run        Record a skill/command/agent execution to mem_item_runs
  team-context           Inject <team-context> from PostgreSQL (FTS-only, SessionStart)
  team-session-init      Inject <team-context> with hybrid search (UserPromptSubmit)

search-structured Input (JSON):
  {"query": "...", "project": "...", "tool_name": "Edit", "file_pattern": "*.py", "date_from": "2024-01-01", "date_to": "2024-12-31"}

record Input (JSON):
  {"event_type": "review|plan|audit|...", "content": "...", "user_prompt": "...", "metadata": {"files_read": [], "files_modified": []}}

sync Input (JSON):
  {"dry_run": false}

import Input (JSON):
  {"types": ["instincts", "adrs", "events"], "repo_root": "/path/to/repo"}
"""


if __name__ == "__main__":  # pragma: no cover
    main()
