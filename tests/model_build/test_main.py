"""__main__ モジュールのユニットテスト（ネットワーク不要）。"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest
from model_build.__main__ import _cmd_clean, _cmd_verify


class TestCmdClean:
    """clean サブコマンドのテスト。"""

    def _make_args(self, out: Path) -> argparse.Namespace:
        """argparse.Namespace を返す。"""
        return argparse.Namespace(out=out)

    def test_clean_removes_parts_and_manifest(self, tmp_path: Path) -> None:
        """part ファイルと manifest.json が削除される。"""
        for i in range(3):
            (tmp_path / f"model.onnx.part{i:02d}").write_bytes(b"x")
        (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
        (tmp_path / "tokenizer.json").write_bytes(b"keep")  # 保持されるはず

        _cmd_clean(self._make_args(tmp_path))

        assert not list(tmp_path.glob("model.onnx.part*"))
        assert not (tmp_path / "manifest.json").exists()
        assert (tmp_path / "tokenizer.json").exists()

    def test_clean_empty_dir_succeeds(self, tmp_path: Path) -> None:
        """対象ファイルがなくてもエラーにならない。"""
        _cmd_clean(self._make_args(tmp_path))  # 例外が発生しないこと

    def test_clean_reports_count(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        """削除ファイル数を出力する。"""
        (tmp_path / "model.onnx.part00").write_bytes(b"x")
        (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")

        _cmd_clean(self._make_args(tmp_path))

        captured = capsys.readouterr()
        assert "2" in captured.out

    def test_clean_nonexistent_dir_reports_and_exits(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """存在しないディレクトリでも例外にならず、メッセージを出力する。"""
        nonexistent = tmp_path / "no_such_dir"
        _cmd_clean(self._make_args(nonexistent))
        captured = capsys.readouterr()
        assert "存在しません" in captured.out


class TestCmdVerify:
    """verify サブコマンドのテスト（verify 本体をモック）。"""

    def _make_args(self, model_dir: Path, cosine_threshold: float = 0.999) -> argparse.Namespace:
        """argparse.Namespace を返す。"""
        return argparse.Namespace(model_dir=model_dir, cosine_threshold=cosine_threshold)

    def test_verify_called_with_correct_args(self, tmp_path: Path) -> None:
        """verify() が正しい引数で呼び出される。"""
        with patch("model_build.verify.verify") as mock_verify:
            _cmd_verify(self._make_args(tmp_path, cosine_threshold=0.95))
            mock_verify.assert_called_once_with(tmp_path, cosine_threshold=0.95)

    def test_verify_propagates_error(self, tmp_path: Path) -> None:
        """verify() が例外を送出すると呼び出し元に伝播する。"""
        with patch("model_build.verify.verify", side_effect=FileNotFoundError("missing")):
            with pytest.raises(FileNotFoundError, match="missing"):
                _cmd_verify(self._make_args(tmp_path))
