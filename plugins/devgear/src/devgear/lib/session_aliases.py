"""
セッションエイリアスを JSON ファイルで永続化します。
読み込み、保存、検索、改名、タイトル更新、クリーンアップまでを一通り扱います。
アトミック書き込みとバックアップ復元でデータ損失を抑えます。
"""

from __future__ import annotations

import json
import platform
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from devgear.lib.core_utils import ensure_dir, get_claude_dir, log, read_file

ALIAS_VERSION = "1.0"

# 有効なエイリアス名パターン
ALIAS_NAME_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")

# 予約済みエイリアス名
RESERVED_ALIASES = frozenset(["list", "help", "remove", "delete", "create", "set"])


def get_aliases_path() -> Path:
    """エイリアスファイルのパスを取得する。

    Returns:
        Path: Path オブジェクトを返します。

    Args:
        引数はありません。

    Raises:
        例外は発生しません。
    """
    return get_claude_dir() / "session-aliases.json"


def get_default_aliases() -> dict[str, Any]:
    """既定のエイリアスファイル構造を返す。

    Returns:
        dict[str, Any]: 情報を格納した辞書を返します。

    Args:
        引数はありません。

    Raises:
        例外は発生しません。
    """
    return {
        "version": ALIAS_VERSION,
        "aliases": {},
        "metadata": {
            "totalCount": 0,
            "lastUpdated": datetime.now().isoformat(),
        },
    }


def load_aliases() -> dict[str, Any]:
    """ファイルからエイリアスを読み込む。

    Returns:
        dict[str, Any]: 情報を格納した辞書を返します。

    Args:
        引数はありません。

    Raises:
        例外は発生しません。
    """
    aliases_path = get_aliases_path()

    if not aliases_path.exists():
        return get_default_aliases()

    content = read_file(aliases_path)
    if not content:
        return get_default_aliases()

    try:
        data = json.loads(content)

        # 構造を検証
        if not data.get("aliases") or not isinstance(data.get("aliases"), dict):
            log("[Aliases] Invalid aliases file structure, resetting")
            return get_default_aliases()

        # version フィールドを保証
        if not data.get("version"):
            data["version"] = ALIAS_VERSION

        # metadata を保証
        if not data.get("metadata"):
            data["metadata"] = {
                "totalCount": len(data["aliases"]),
                "lastUpdated": datetime.now().isoformat(),
            }

        return data
    except json.JSONDecodeError as err:
        log(f"[Aliases] Error parsing aliases file: {err}")
        return get_default_aliases()


def save_aliases(aliases: dict[str, Any]) -> bool:
    """エイリアスをアトミック書き込みでファイル保存する。

    Args:
        aliases: 代替見出し名の一覧

    Returns:
        bool: 条件を満たす場合は True、そうでない場合は False。

    Raises:
        例外は発生しません。
    """
    aliases_path = get_aliases_path()
    temp_path = aliases_path.with_suffix(".json.tmp")
    backup_path = aliases_path.with_suffix(".json.bak")

    try:
        # メタデータを更新
        aliases["metadata"] = {
            "totalCount": len(aliases.get("aliases", {})),
            "lastUpdated": datetime.now().isoformat(),
        }

        content = json.dumps(aliases, indent=2)

        # ディレクトリの存在を保証
        ensure_dir(aliases_path.parent)

        # ファイルが存在する場合はバックアップを作成
        if aliases_path.exists():
            shutil.copy2(aliases_path, backup_path)

        # アトミック書き込み: 一時ファイルに書き込み後、リネーム
        temp_path.write_text(content, encoding="utf-8")

        # Windows では宛先が存在すると rename が失敗する
        if platform.system() == "Windows" and aliases_path.exists():
            aliases_path.unlink()
        temp_path.rename(aliases_path)

        # 成功時はバックアップを削除
        if backup_path.exists():
            backup_path.unlink()

        return True
    except Exception as err:
        log(f"[Aliases] Error saving aliases: {err}")

        # バックアップがあれば復元
        if backup_path.exists():
            try:
                shutil.copy2(backup_path, aliases_path)
                log("[Aliases] Restored from backup")
            except Exception as restore_err:
                log(f"[Aliases] Failed to restore backup: {restore_err}")

        # 一時ファイルをクリーンアップ
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception as e:
            log(f"[Aliases] Failed to cleanup temp file: {e}")

        return False


@dataclass
class AliasInfo:
    """解決済みエイリアス情報。"""

    alias: str
    session_path: str
    created_at: str
    title: str | None = None


def resolve_alias(alias: str) -> AliasInfo | None:
    """エイリアスを解決してセッションパスを取得する。

    Args:
        alias: エイリアス名

    Returns:
        AliasInfo | None: AliasInfo を返します。見つからない場合は None です。

    Raises:
        例外は発生しません。
    """
    if not alias:
        return None

    # エイリアス名を検証
    if not ALIAS_NAME_REGEX.match(alias):
        return None

    data = load_aliases()
    alias_data = data["aliases"].get(alias)

    if not alias_data:
        return None

    return AliasInfo(
        alias=alias,
        session_path=alias_data["sessionPath"],
        created_at=alias_data["createdAt"],
        title=alias_data.get("title"),
    )


@dataclass
class SetAliasResult:
    """エイリアス設定結果。"""

    success: bool
    error: str | None = None
    is_new: bool | None = None
    alias: str | None = None
    session_path: str | None = None
    title: str | None = None


def set_alias(
    alias: str,
    session_path: str,
    title: str | None = None,
) -> SetAliasResult:
    """セッションのエイリアスを設定または更新する。

    Args:
        alias: エイリアス名
        session_path: セッションファイルのパス
        title: タイトル

    Returns:
        SetAliasResult: 処理結果を返します。

    Raises:
        例外は発生しません。
    """
    # エイリアス名を検証
    if not alias:
        return SetAliasResult(success=False, error="Alias name cannot be empty")

    # セッションパスを検証
    if not session_path or not isinstance(session_path, str) or not session_path.strip():
        return SetAliasResult(success=False, error="Session path cannot be empty")

    if len(alias) > 128:
        return SetAliasResult(success=False, error="Alias name cannot exceed 128 characters")

    if not ALIAS_NAME_REGEX.match(alias):
        return SetAliasResult(
            success=False,
            error="Alias name must contain only letters, numbers, dashes, and underscores",
        )

    if alias.lower() in RESERVED_ALIASES:
        return SetAliasResult(success=False, error=f"'{alias}' is a reserved alias name")

    data = load_aliases()
    existing = data["aliases"].get(alias)
    is_new = existing is None

    now = datetime.now().isoformat()
    data["aliases"][alias] = {
        "sessionPath": session_path,
        "createdAt": existing["createdAt"] if existing else now,
        "updatedAt": now,
        "title": title,
    }

    if save_aliases(data):
        return SetAliasResult(
            success=True,
            is_new=is_new,
            alias=alias,
            session_path=session_path,
            title=title,
        )

    return SetAliasResult(success=False, error="Failed to save alias")


@dataclass
class AliasListItem:
    """エイリアス一覧の項目。"""

    name: str
    session_path: str
    created_at: str | None
    updated_at: str | None
    title: str | None


def list_aliases(
    *,
    search: str | None = None,
    limit: int | None = None,
) -> list[AliasListItem]:
    """すべてのエイリアスを一覧表示する。

    Args:
        search: 検索文字列
        limit: 返す件数の上限

    Returns:
        list[AliasListItem]: AliasListItem の一覧を返します。

    Raises:
        例外は発生しません。
    """
    data = load_aliases()

    aliases = [
        AliasListItem(
            name=name,
            session_path=info["sessionPath"],
            created_at=info.get("createdAt"),
            updated_at=info.get("updatedAt"),
            title=info.get("title"),
        )
        for name, info in data["aliases"].items()
    ]

    # 更新時刻で並べ替え（新しい順）
    def get_sort_key(a: AliasListItem) -> float:
        """エイリアス項目のソートキーを取得する（更新時刻の降順）。

        タイムスタンプが不正な場合は 0 を返し、最後尾に配置する。

        Args:
            a: 処理に渡す a の値です。

        Returns:
            処理結果を返します。

        Raises:
            例外は発生しません。
        """
        try:
            ts = a.updated_at or a.created_at
            if ts:
                return -datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError) as e:
            log(f"[Aliases] Invalid timestamp on '{a.name}': {e}")
        return 0

    aliases.sort(key=get_sort_key)

    # 検索フィルタを適用
    if search:
        search_lower = search.lower()
        aliases = [
            a for a in aliases if search_lower in a.name.lower() or (a.title and search_lower in a.title.lower())
        ]

    # 件数上限を適用
    if limit and limit > 0:
        aliases = aliases[:limit]

    return aliases


@dataclass
class DeleteAliasResult:
    """エイリアス削除結果。"""

    success: bool
    error: str | None = None
    alias: str | None = None
    deleted_session_path: str | None = None


def delete_alias(alias: str) -> DeleteAliasResult:
    """エイリアスを削除する。

    Args:
        alias: エイリアス名

    Returns:
        DeleteAliasResult: 処理結果を返します。

    Raises:
        例外は発生しません。
    """
    data = load_aliases()

    if alias not in data["aliases"]:
        return DeleteAliasResult(success=False, error=f"Alias '{alias}' not found")

    deleted = data["aliases"][alias]
    del data["aliases"][alias]

    if save_aliases(data):
        return DeleteAliasResult(
            success=True,
            alias=alias,
            deleted_session_path=deleted["sessionPath"],
        )

    return DeleteAliasResult(success=False, error="Failed to delete alias")


@dataclass
class RenameAliasResult:
    """エイリアス改名結果。"""

    success: bool
    error: str | None = None
    old_alias: str | None = None
    new_alias: str | None = None
    session_path: str | None = None


def rename_alias(old_alias: str, new_alias: str) -> RenameAliasResult:
    """エイリアス名を変更する。

    Args:
        old_alias: 変更前のエイリアス名
        new_alias: 新しいエイリアス名

    Returns:
        RenameAliasResult: 処理結果を返します。

    Raises:
        例外は発生しません。
    """
    data = load_aliases()

    if old_alias not in data["aliases"]:
        return RenameAliasResult(success=False, error=f"Alias '{old_alias}' not found")

    # 新しいエイリアス名を検証
    if not new_alias:
        return RenameAliasResult(success=False, error="New alias name cannot be empty")

    if len(new_alias) > 128:
        return RenameAliasResult(
            success=False,
            error="New alias name cannot exceed 128 characters",
        )

    if not ALIAS_NAME_REGEX.match(new_alias):
        return RenameAliasResult(
            success=False,
            error="New alias name must contain only letters, numbers, dashes, and underscores",
        )

    if new_alias.lower() in RESERVED_ALIASES:
        return RenameAliasResult(
            success=False,
            error=f"'{new_alias}' is a reserved alias name",
        )

    if new_alias in data["aliases"]:
        return RenameAliasResult(
            success=False,
            error=f"Alias '{new_alias}' already exists",
        )

    alias_data = data["aliases"][old_alias]
    del data["aliases"][old_alias]

    alias_data["updatedAt"] = datetime.now().isoformat()
    data["aliases"][new_alias] = alias_data

    if save_aliases(data):
        return RenameAliasResult(
            success=True,
            old_alias=old_alias,
            new_alias=new_alias,
            session_path=alias_data["sessionPath"],
        )

    # 失敗時に復元
    data["aliases"][old_alias] = alias_data
    del data["aliases"][new_alias]
    save_aliases(data)

    return RenameAliasResult(
        success=False,
        error="Failed to save renamed alias — rolled back to original",
    )


def resolve_session_alias(alias_or_id: str) -> str:
    """エイリアスからセッションパスを取得する（簡易関数）。

    Args:
        alias_or_id: alias or の識別子

    Returns:
        str: 文字列を返します。

    Raises:
        例外は発生しません。
    """
    resolved = resolve_alias(alias_or_id)
    if resolved:
        return resolved.session_path

    return alias_or_id


@dataclass
class UpdateTitleResult:
    """エイリアスタイトル更新結果。"""

    success: bool
    error: str | None = None
    alias: str | None = None
    title: str | None = None


def update_alias_title(alias: str, title: str | None) -> UpdateTitleResult:
    """エイリアスのタイトルを更新する。

    Args:
        alias: エイリアス名
        title: タイトル

    Returns:
        UpdateTitleResult: 処理結果を返します。

    Raises:
        例外は発生しません。
    """
    if title is not None and not isinstance(title, str):
        return UpdateTitleResult(success=False, error="Title must be a string or null")

    data = load_aliases()

    if alias not in data["aliases"]:
        return UpdateTitleResult(success=False, error=f"Alias '{alias}' not found")

    data["aliases"][alias]["title"] = title
    data["aliases"][alias]["updatedAt"] = datetime.now().isoformat()

    if save_aliases(data):
        return UpdateTitleResult(success=True, alias=alias, title=title)

    return UpdateTitleResult(success=False, error="Failed to update alias title")


@dataclass
class SessionAliasInfo:
    """特定セッションのエイリアス情報。"""

    name: str
    created_at: str | None
    title: str | None


def get_aliases_for_session(session_path: str) -> list[SessionAliasInfo]:
    """特定セッションに紐づくすべてのエイリアスを取得する。

    Args:
        session_path: セッションファイルのパス

    Returns:
        list[SessionAliasInfo]: SessionAliasInfo の一覧を返します。

    Raises:
        例外は発生しません。
    """
    data = load_aliases()
    aliases = []

    for name, info in data["aliases"].items():
        if info["sessionPath"] == session_path:
            aliases.append(
                SessionAliasInfo(
                    name=name,
                    created_at=info.get("createdAt"),
                    title=info.get("title"),
                )
            )

    return aliases


@dataclass
class CleanupResult:
    """エイリアスクリーンアップ結果。"""

    success: bool
    total_checked: int
    removed: int
    removed_aliases: list[dict[str, str]]
    error: str | None = None


def cleanup_aliases(session_exists: Callable[[str], bool]) -> CleanupResult:
    """存在しないセッション向けのエイリアスをクリーンアップする。

    Args:
        session_exists: セッション存在確認関数

    Returns:
        CleanupResult: 処理結果を返します。

    Raises:
        例外は発生しません。
    """
    if not callable(session_exists):
        return CleanupResult(
            success=False,
            total_checked=0,
            removed=0,
            removed_aliases=[],
            error="session_exists must be a function",
        )

    data = load_aliases()
    removed: list[dict[str, str]] = []

    aliases_to_remove = []
    for name, info in data["aliases"].items():
        if not session_exists(info["sessionPath"]):
            removed.append({"name": name, "sessionPath": info["sessionPath"]})
            aliases_to_remove.append(name)

    for name in aliases_to_remove:
        del data["aliases"][name]

    total_checked = len(data["aliases"]) + len(removed)

    if removed and not save_aliases(data):
        log("[Aliases] Failed to save after cleanup")
        return CleanupResult(
            success=False,
            total_checked=total_checked,
            removed=len(removed),
            removed_aliases=removed,
            error="Failed to save after cleanup",
        )

    return CleanupResult(
        success=True,
        total_checked=total_checked,
        removed=len(removed),
        removed_aliases=removed,
    )


__all__ = [
    "ALIAS_VERSION",
    "AliasInfo",
    "AliasListItem",
    "CleanupResult",
    "DeleteAliasResult",
    "RenameAliasResult",
    "SessionAliasInfo",
    "SetAliasResult",
    "UpdateTitleResult",
    "cleanup_aliases",
    "delete_alias",
    "get_aliases_for_session",
    "get_aliases_path",
    "list_aliases",
    "load_aliases",
    "rename_alias",
    "resolve_alias",
    "resolve_session_alias",
    "save_aliases",
    "set_alias",
    "update_alias_title",
]
