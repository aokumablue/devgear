"""c-sessions のプラグイン内ランタイム。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from devgear.lib.session_aliases import (
    AliasListItem,
    delete_alias,
    get_aliases_for_session,
    list_aliases,
    resolve_alias,
    set_alias,
)
from devgear.lib.session_manager import (
    SessionDetail,
    SessionRecord,
    get_all_sessions,
    get_session_by_id,
    get_session_content,
    get_session_size,
    get_session_stats,
    parse_session_metadata,
)


def _normalize_session_target(target: str) -> str:
    """セッション識別子を検索用の値に正規化する。"""

    normalized = target.strip()
    if not normalized:
        return normalized
    return Path(normalized).name


def _build_alias_map(aliases: list[AliasListItem]) -> dict[str, str]:
    """セッションパスとエイリアス名の対応を構築する。"""

    alias_map: dict[str, str] = {}
    for alias in aliases:
        alias_map[alias.session_path] = alias.name
        alias_map[Path(alias.session_path).name] = alias.name
    return alias_map


def _print_session_list(sessions: list[SessionRecord], total: int) -> None:
    """セッション一覧を整形して出力する。"""

    alias_map = _build_alias_map(list_aliases())
    print(f"Sessions (showing {len(sessions)} of {total}):\n")
    print("ID        Date        Time     Branch       Worktree           Alias")
    print("────────────────────────────────────────────────────────────────────")

    for session in sessions:
        alias = alias_map.get(session.filename, "")
        metadata = parse_session_metadata(get_session_content(session.session_path))
        identifier = "(none)" if session.short_id == "no-id" else session.short_id[:8]
        time_value = session.modified_time.strftime("%H:%M")
        branch = (metadata.branch or "-")[:12]
        worktree = Path(metadata.worktree).name[:18] if metadata.worktree else "-"
        print(
            f"{identifier.ljust(8)} {session.date}  {time_value}   "
            f"{branch.ljust(12)} {worktree.ljust(18)} {alias}"
        )


def _handle_list(args: list[str]) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--date")
    parser.add_argument("--search")
    parsed = parser.parse_args(args)

    result = get_all_sessions(limit=parsed.limit, date=parsed.date, search=parsed.search)
    _print_session_list(result.sessions, result.total)
    return 0


def _print_session_detail(session: SessionDetail) -> None:
    """セッション詳細を整形して出力する。"""

    stats = session.stats or get_session_stats(session.content or "")
    aliases = get_aliases_for_session(session.filename)

    print(f"Session: {session.filename}")
    print(f"Path: {session.session_path}\n")
    print(
        "  Lines: "
        f"{stats.line_count}, Total: {stats.total_items}, Completed: {stats.completed_items}, "
        f"Size: {get_session_size(session.session_path)}"
    )
    if aliases:
        print("Aliases: " + ", ".join(alias.name for alias in aliases))
    if session.metadata and session.metadata.project:
        print(f"Project: {session.metadata.project}")
    if session.metadata and session.metadata.branch:
        print(f"Branch: {session.metadata.branch}")
    if session.metadata and session.metadata.worktree:
        print(f"Worktree: {session.metadata.worktree}")


def _handle_load(args: list[str]) -> int:
    if len(args) != 1:
        print("Usage: /c-sessions load <id|alias>")
        return 1

    requested = args[0]
    resolved = resolve_alias(requested)
    session_id = _normalize_session_target(resolved.session_path if resolved else requested)
    session = get_session_by_id(session_id, True)

    if not session:
        print(f"Session not found: {requested}")
        return 1

    _print_session_detail(session)
    return 0


def _handle_alias(args: list[str]) -> int:
    if not args:
        print("Usage: /c-sessions alias <id> <name>")
        return 1

    if args[0] == "--remove":
        if len(args) != 2:
            print("Usage: /c-sessions alias --remove <name>")
            return 1
        result = delete_alias(args[1])
        if result.success:
            print(f"Alias removed: {result.alias}")
            return 0
        print(f"Error: {result.error}")
        return 1

    if len(args) != 2:
        print("Usage: /c-sessions alias <id> <name>")
        return 1

    session_id, alias_name = args
    session = get_session_by_id(_normalize_session_target(session_id))
    if not session:
        print(f"Session not found: {session_id}")
        return 1

    result = set_alias(alias_name, session.filename)
    if result.success:
        print(f"Alias created: {alias_name} -> {session.filename}")
        return 0

    print(f"Error: {result.error}")
    return 1


def _handle_aliases() -> int:
    aliases = list_aliases()
    if not aliases:
        print("No aliases found.")
        return 0

    print("Alias      Session Path")
    print("────────────────────────────────────────────────────────")
    for alias in aliases:
        print(f"{alias.name.ljust(10)} {alias.session_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """c-sessions の CLI エントリポイント。"""

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("Usage: /c-sessions [list|load|alias|aliases]")
        return 0

    command = args[0]
    if command == "list":
        return _handle_list(args[1:])
    if command == "load":
        return _handle_load(args[1:])
    if command == "alias":
        return _handle_alias(args[1:])
    if command == "aliases":
        return _handle_aliases()

    print(f"Unknown command: {command}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

