"""
セッションファイルを探索し、メタデータを解析します。
ファイル名からの識別子抽出、Markdown 内容の解析、CRUD 相当の操作をまとめます。
セッション一覧や詳細表示に必要な共通処理を提供します。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from devgear.lib.core_utils import get_session_search_dirs, get_sessions_dir, log, read_file

# セッションファイル名パターン: YYYY-MM-DD-[session-id]-session.tmp
SESSION_FILENAME_REGEX = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-([a-zA-Z0-9_][a-zA-Z0-9_-]*))?-session\.tmp$")


@dataclass
class SessionMetadata:
    """セッションファイル名から解析したメタデータ。"""

    filename: str
    short_id: str
    date: str
    datetime: datetime


@dataclass
class SessionRecord:
    """ファイル情報を含む完全なセッションレコード。"""

    filename: str
    short_id: str
    date: str
    datetime: datetime
    session_path: str
    has_content: bool
    size: int
    modified_time: datetime
    created_time: datetime


@dataclass
class ParsedSessionMetadata:
    """セッション内容から解析したメタデータ。"""

    title: str | None = None
    date: str | None = None
    started: str | None = None
    last_updated: str | None = None
    project: str | None = None
    branch: str | None = None
    worktree: str | None = None
    completed: list[str] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    notes: str = ""
    context: str = ""


@dataclass
class SessionStats:
    """セッションの統計情報。"""

    total_items: int
    completed_items: int
    in_progress_items: int
    line_count: int
    has_notes: bool
    has_context: bool


def _section_heading_pattern(*headings: str) -> str:
    """見出し候補から正規表現パターンを生成する。

    Args:
        headings: 見出し候補の一覧。

    Returns:
        str: 生成した正規表現パターン。

    Raises:
        例外は発生しません。
    """
    return "|".join(re.escape(heading) for heading in headings)


def parse_session_filename(filename: str) -> SessionMetadata | None:
    """セッションファイル名を解析してメタデータを抽出する。

    Args:
        filename: ファイル名

    Returns:
        SessionMetadata | None: SessionMetadata を返します。見つからない場合は None です。

    Raises:
        例外は発生しません。
    """
    if not filename or not isinstance(filename, str):
        return None

    match = SESSION_FILENAME_REGEX.match(filename)
    if not match:
        return None

    date_str = match.group(1)

    # 日付の構成要素を検証
    try:
        year, month, day = map(int, date_str.split("-"))
        if month < 1 or month > 12 or day < 1 or day > 31:
            return None

        # 存在しない日付をチェック
        d = datetime(year, month, day)
        if d.month != month or d.day != day:
            return None
    except ValueError:
        return None

    short_id = match.group(2) or "no-id"

    return SessionMetadata(
        filename=filename,
        short_id=short_id,
        date=date_str,
        datetime=datetime(year, month, day),
    )


def get_session_path(filename: str) -> Path:
    """セッションファイルのフルパスを取得する。

    Args:
        filename: ファイル名

    Returns:
        Path: 取得結果を返します。

    Raises:
        例外は発生しません。
    """
    return get_sessions_dir() / filename


def _build_session_record(
    session_path: Path,
    metadata: SessionMetadata,
) -> SessionRecord | None:
    """パスとメタデータからセッションレコードを構築する。

    Args:
        session_path: セッションファイルのパス
        metadata: メタデータ

    Returns:
        SessionRecord | None: SessionRecord を返します。見つからない場合は None です。

    Raises:
        例外は発生しません。
    """
    try:
        stats = session_path.stat()
    except OSError as error:
        log(f"[SessionManager] Error stating session {session_path}: {error}")
        return None

    return SessionRecord(
        filename=metadata.filename,
        short_id=metadata.short_id,
        date=metadata.date,
        datetime=metadata.datetime,
        session_path=str(session_path),
        has_content=stats.st_size > 0,
        size=stats.st_size,
        modified_time=datetime.fromtimestamp(stats.st_mtime),
        created_time=datetime.fromtimestamp(stats.st_ctime),
    )


def _get_session_candidates(
    *,
    date: str | None = None,
    search: str | None = None,
) -> list[SessionRecord]:
    """任意のフィルタ付きでセッション候補を取得する。

    Args:
        date: 日付文字列
        search: 検索文字列

    Returns:
        list[SessionRecord]: SessionRecord の一覧を返します。

    Raises:
        例外は発生しません。
    """
    candidates: list[SessionRecord] = []

    for sessions_dir in get_session_search_dirs():
        if not sessions_dir.exists():
            continue

        try:
            entries = list(sessions_dir.iterdir())
        except OSError as error:
            log(f"[SessionManager] Error reading sessions directory {sessions_dir}: {error}")
            continue

        for entry in entries:
            if not entry.is_file() or not entry.name.endswith(".tmp"):
                continue

            metadata = parse_session_filename(entry.name)
            if not metadata:
                continue

            if date and metadata.date != date:
                continue
            if search and search not in metadata.short_id:
                continue

            record = _build_session_record(entry, metadata)
            if record:
                candidates.append(record)

    # ファイル名で重複除去
    seen: set[str] = set()
    deduped: list[SessionRecord] = []
    for session in candidates:
        if session.filename not in seen:
            seen.add(session.filename)
            deduped.append(session)

    # 更新時刻でソート（新しい順）
    deduped.sort(key=lambda s: s.modified_time, reverse=True)
    return deduped


def _session_matches_id(metadata: SessionMetadata, normalized_id: str) -> bool:
    """セッションが指定 ID に一致するか確認する。

    Args:
        metadata: メタデータ
        normalized_id: normalized_id の値

    Returns:
        bool: 条件を満たす場合は True、そうでない場合は False。

    Raises:
        例外は発生しません。
    """
    filename = metadata.filename
    short_id_match = metadata.short_id != "no-id" and metadata.short_id.startswith(normalized_id)
    filename_match = filename == normalized_id or filename == f"{normalized_id}.tmp"
    no_id_match = metadata.short_id == "no-id" and filename == f"{normalized_id}-session.tmp"

    return short_id_match or filename_match or no_id_match


def get_session_content(session_path: str | Path) -> str | None:
    """セッションの Markdown 内容を読み込む。

    Args:
        session_path: セッションファイルのパス

    Returns:
        str | None: str を返します。見つからない場合は None です。

    Raises:
        例外は発生しません。
    """
    return read_file(session_path)


def parse_session_metadata(content: str | None) -> ParsedSessionMetadata:
    """Markdown 内容からセッションメタデータを解析する。

    Args:
        content: 内容

    Returns:
        ParsedSessionMetadata: 解析結果を返します。

    Raises:
        例外は発生しません。
    """
    metadata = ParsedSessionMetadata()

    if not content:
        return metadata

    # 最初の見出しからタイトルを抽出
    title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if title_match:
        metadata.title = title_match.group(1).strip()

    # 日付を抽出
    date_match = re.search(r"\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})", content)
    if date_match:
        metadata.date = date_match.group(1)

    # 開始時刻を抽出
    started_match = re.search(r"\*\*Started:\*\*\s*([\d:]+)", content)
    if started_match:
        metadata.started = started_match.group(1)

    # 最終更新時刻を抽出
    updated_match = re.search(r"\*\*Last Updated:\*\*\s*([\d:]+)", content)
    if updated_match:
        metadata.last_updated = updated_match.group(1)

    # コントロールプレーンのメタデータを抽出
    project_match = re.search(r"\*\*Project:\*\*\s*(.+)$", content, re.MULTILINE)
    if project_match:
        metadata.project = project_match.group(1).strip()

    branch_match = re.search(r"\*\*Branch:\*\*\s*(.+)$", content, re.MULTILINE)
    if branch_match:
        metadata.branch = branch_match.group(1).strip()

    worktree_match = re.search(r"\*\*Worktree:\*\*\s*(.+)$", content, re.MULTILINE)
    if worktree_match:
        metadata.worktree = worktree_match.group(1).strip()

    # 完了項目を抽出
    completed_section = re.search(
        rf"### (?:{_section_heading_pattern('Completed', '完了済み')})\s*\n([\s\S]*?)(?=###|\n\n|$)",
        content,
    )
    if completed_section:
        items = re.findall(r"- \[x\]\s*(.+)", completed_section.group(1))
        metadata.completed = [item.strip() for item in items]

    # 進行中項目を抽出
    progress_section = re.search(
        rf"### (?:{_section_heading_pattern('In Progress', '進行中')})\s*\n([\s\S]*?)(?=###|\n\n|$)",
        content,
    )
    if progress_section:
        items = re.findall(r"- \[ \]\s*(.+)", progress_section.group(1))
        metadata.in_progress = [item.strip() for item in items]

    # メモを抽出
    notes_section = re.search(
        rf"### (?:{_section_heading_pattern('Notes for Next Session', '次回セッションへの引継ぎ')})\s*\n([\s\S]*?)(?=###|\n\n|$)",
        content,
    )
    if notes_section:
        metadata.notes = notes_section.group(1).strip()

    # 読み込むコンテキストを抽出
    context_section = re.search(
        rf"### (?:{_section_heading_pattern('Context to Load', '読み込むコンテキスト')})\s*\n```\n([\s\S]*?)```",
        content,
    )
    if context_section:
        metadata.context = context_section.group(1).strip()

    return metadata


def get_session_stats(session_path_or_content: str) -> SessionStats:
    """セッションの統計情報を計算する。

    Args:
        session_path_or_content: セッションファイルのパス、または事前読み込み済みの内容

    Returns:
        SessionStats: 取得結果を返します。

    Raises:
        例外は発生しません。
    """
    # 入力がファイルパスらしいか判定
    looks_like_path = (
        isinstance(session_path_or_content, str)
        and "\n" not in session_path_or_content
        and session_path_or_content.endswith(".tmp")
        and (
            session_path_or_content.startswith("/")
            or (len(session_path_or_content) > 2 and session_path_or_content[1] == ":")
        )
    )

    content = get_session_content(session_path_or_content) if looks_like_path else session_path_or_content

    metadata = parse_session_metadata(content)

    return SessionStats(
        total_items=len(metadata.completed) + len(metadata.in_progress),
        completed_items=len(metadata.completed),
        in_progress_items=len(metadata.in_progress),
        line_count=len(content.split("\n")) if content else 0,
        has_notes=bool(metadata.notes),
        has_context=bool(metadata.context),
    )


@dataclass
class SessionListResult:
    """セッション一覧取得結果。"""

    sessions: list[SessionRecord]
    total: int
    offset: int
    limit: int
    has_more: bool


def get_all_sessions(
    *,
    limit: int = 50,
    offset: int = 0,
    date: str | None = None,
    search: str | None = None,
) -> SessionListResult:
    """任意のフィルタとページネーション付きで全セッションを取得する。

    Args:
        limit: 返す件数の上限
        offset: offset の値
        date: 日付文字列
        search: 検索文字列

    Returns:
        SessionListResult: 取得結果を返します。

    Raises:
        例外は発生しません。
    """
    # offset と limit を範囲内に丸める
    offset = max(0, int(offset)) if offset is not None else 0
    limit = max(1, int(limit)) if limit is not None else 50

    sessions = _get_session_candidates(date=date, search=search)

    if not sessions:
        return SessionListResult(
            sessions=[],
            total=0,
            offset=offset,
            limit=limit,
            has_more=False,
        )

    paginated = sessions[offset : offset + limit]

    return SessionListResult(
        sessions=paginated,
        total=len(sessions),
        offset=offset,
        limit=limit,
        has_more=offset + limit < len(sessions),
    )


@dataclass
class SessionDetail:
    """セッションの詳細情報。"""

    filename: str
    short_id: str
    date: str
    datetime: datetime
    session_path: str
    has_content: bool
    size: int
    modified_time: datetime
    created_time: datetime
    content: str | None = None
    metadata: ParsedSessionMetadata | None = None
    stats: SessionStats | None = None


def get_session_by_id(
    session_id: str,
    include_content: bool = False,
) -> SessionDetail | None:
    """ID で単一のセッションを取得する。

    Args:
        session_id: セッションID
        include_content: セッション内容を含めるかどうか

    Returns:
        SessionDetail | None: SessionDetail を返します。見つからない場合は None です。

    Raises:
        例外は発生しません。
    """
    if not isinstance(session_id, str):
        return None

    normalized_id = session_id.strip()
    if not normalized_id:
        return None

    # 一致するセッションを検索
    for sessions_dir in get_session_search_dirs():
        if not sessions_dir.exists():
            continue

        try:
            entries = list(sessions_dir.iterdir())
        except OSError:
            continue

        for entry in entries:
            if not entry.is_file() or not entry.name.endswith(".tmp"):
                continue

            metadata = parse_session_filename(entry.name)
            if not metadata or not _session_matches_id(metadata, normalized_id):
                continue

            record = _build_session_record(entry, metadata)
            if not record:
                continue

            detail = SessionDetail(
                filename=record.filename,
                short_id=record.short_id,
                date=record.date,
                datetime=record.datetime,
                session_path=record.session_path,
                has_content=record.has_content,
                size=record.size,
                modified_time=record.modified_time,
                created_time=record.created_time,
            )

            if include_content:
                detail.content = get_session_content(record.session_path)
                detail.metadata = parse_session_metadata(detail.content)
                detail.stats = get_session_stats(detail.content or "")

            return detail

    return None


def get_session_title(session_path: str | Path) -> str:
    """内容からセッションタイトルを取得する。

    Args:
        session_path: セッションファイルのパス

    Returns:
        str: 取得結果を返します。

    Raises:
        例外は発生しません。
    """
    content = get_session_content(session_path)
    metadata = parse_session_metadata(content)
    return metadata.title or "Untitled Session"


def get_session_size(session_path: str | Path) -> str:
    """セッションサイズを人間が読みやすい形式に整形する。

    Args:
        session_path: セッションファイルのパス

    Returns:
        str: 取得結果を返します。

    Raises:
        例外は発生しません。
    """
    try:
        size = Path(session_path).stat().st_size
    except OSError:
        return "0 B"

    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def write_session_content(session_path: str | Path, content: str) -> bool:
    """セッション内容をファイルに書き込む。

    Args:
        session_path: セッションファイルのパス
        content: 内容

    Returns:
        bool: 条件を満たす場合は True、そうでない場合は False。

    Raises:
        例外は発生しません。
    """
    try:
        Path(session_path).write_text(content, encoding="utf-8")
        return True
    except OSError as err:
        log(f"[SessionManager] Error writing session: {err}")
        return False


def append_session_content(session_path: str | Path, content: str) -> bool:
    """セッションに内容を追記する。

    Args:
        session_path: セッションファイルのパス
        content: 内容

    Returns:
        bool: 条件を満たす場合は True、そうでない場合は False。

    Raises:
        例外は発生しません。
    """
    try:
        with open(session_path, "a", encoding="utf-8") as f:
            f.write(content)
        return True
    except OSError as err:
        log(f"[SessionManager] Error appending to session: {err}")
        return False


def delete_session(session_path: str | Path) -> bool:
    """セッションファイルを削除する。

    Args:
        session_path: セッションファイルのパス

    Returns:
        bool: 条件を満たす場合は True、そうでない場合は False。

    Raises:
        例外は発生しません。
    """
    try:
        path = Path(session_path)
        if path.exists():
            path.unlink()
            return True
        return False
    except OSError as err:
        log(f"[SessionManager] Error deleting session: {err}")
        return False


def session_exists(session_path: str | Path) -> bool:
    """セッションが存在するか確認する。

    Args:
        session_path: セッションファイルのパス

    Returns:
        bool: 条件を満たす場合は True、そうでない場合は False。

    Raises:
        例外は発生しません。
    """
    try:
        return Path(session_path).is_file()
    except OSError:
        return False


__all__ = [
    "ParsedSessionMetadata",
    "SessionDetail",
    "SessionListResult",
    "SessionMetadata",
    "SessionRecord",
    "SessionStats",
    "append_session_content",
    "delete_session",
    "get_all_sessions",
    "get_session_by_id",
    "get_session_content",
    "get_session_path",
    "get_session_size",
    "get_session_stats",
    "get_session_title",
    "parse_session_filename",
    "parse_session_metadata",
    "session_exists",
    "write_session_content",
]
