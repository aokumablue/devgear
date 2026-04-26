"""セッション状態追跡でセッション終了をマーク

トリガー: stop:session:end:marker
入力: セッションメタデータを含む JSON
出力: 入力を変更せずにパススルー
終了: 0（常に成功）
"""

from __future__ import annotations

from devgear.hooks.hook_common import read_raw_stdin, write_stdout


def main() -> int:
    """セッション終了時のマーカーとして標準入力を標準出力に転送する。

    Args:
        引数はありません（標準入力から読み取る）。

    Returns:
        終了コード（0: 成功）

    Raises:
        例外は発生しません。
    """
    write_stdout(read_raw_stdin())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
