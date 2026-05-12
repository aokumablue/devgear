"""mem CLI: sync handlers."""

from __future__ import annotations

import json
from typing import Any


def handle_sync(settings, stdin_data: dict[str, Any]) -> None:
    """PostgreSQL への同期を実行する。"""
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


def handle_sync_check(settings, *, log: Any) -> None:
    """同期間隔をチェックし、必要なら同期を実行する。"""
    from devgear.mem.sync import should_sync, sync_to_postgres

    if not should_sync(settings):
        log.debug("sync-check: スキップ")
        return

    log.info("sync-check: 同期実行")
    result = sync_to_postgres(settings)

    if not result.success:
        log.warning("sync-check: 同期失敗 - %s", result.error)
