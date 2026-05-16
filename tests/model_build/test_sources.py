"""sources サブコマンドのユニットテスト（ネットワーク不要）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from model_build.__main__ import _cmd_sources


def _make_manifest(tmp_path: Path, parts: int = 2) -> Path:
    """テスト用 manifest.json を生成して返す。"""
    manifest = {
        "model_name": "cl-nagoya/ruri-v3-310m",
        "hf_revision": "a" * 40,
        "quantization": "fp16",
        "embedding_dim": 768,
        "tokenizer_max_length": 512,
        "merged_sha256": "e" * 64,
        "parts": [
            {"name": f"model.onnx.part{i:02d}", "size": 100, "sha256": f"{i:064d}"}
            for i in range(parts)
        ],
        "auxiliary_files": [
            {"name": "tokenizer.json", "sha256": "f" * 64},
            {"name": "config.json", "sha256": "d" * 64},
        ],
        "created_at": "2026-01-01T00:00:00+00:00",
        "tool_version": "model_build/0.1.0",
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return p


def _make_args(
    model_dir: Path,
    out: Path,
    git_remote: str = "git@github.com:example/repo.git",
) -> argparse.Namespace:
    """argparse.Namespace を返す。"""
    return argparse.Namespace(model_dir=model_dir, out=out, git_remote=git_remote)


_FAKE_SHA = "a" * 40


class TestCmdSources:
    """sources サブコマンドのテスト。"""

    def test_generates_model_sources_json(self, tmp_path: Path) -> None:
        """model_sources.json が生成される。"""
        _make_manifest(tmp_path)
        out = tmp_path / "model_sources.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            _cmd_sources(_make_args(tmp_path, out))

        assert out.exists()

    def test_sources_schema_version(self, tmp_path: Path) -> None:
        """schema_version が 1 である。"""
        _make_manifest(tmp_path)
        out = tmp_path / "model_sources.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            _cmd_sources(_make_args(tmp_path, out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1

    def test_sources_git_commit_pinned(self, tmp_path: Path) -> None:
        """git_commit に subprocess の出力が使われる。"""
        _make_manifest(tmp_path)
        out = tmp_path / "model_sources.json"
        expected_sha = "b" * 40

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = expected_sha + "\n"
            _cmd_sources(_make_args(tmp_path, out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["git_commit"] == expected_sha

    def test_sources_git_remote_preserved(self, tmp_path: Path) -> None:
        """指定した git_remote が記録される。"""
        _make_manifest(tmp_path)
        out = tmp_path / "model_sources.json"
        remote = "git@github.com:custom/repo.git"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            _cmd_sources(_make_args(tmp_path, out, git_remote=remote))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["git_remote"] == remote

    def test_sources_parts_count(self, tmp_path: Path) -> None:
        """manifest の parts が正しく転記される。"""
        _make_manifest(tmp_path, parts=3)
        out = tmp_path / "model_sources.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            _cmd_sources(_make_args(tmp_path, out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["parts"]) == 3

    def test_sources_merged_sha256_preserved(self, tmp_path: Path) -> None:
        """manifest の merged_sha256 が保持される。"""
        _make_manifest(tmp_path)
        out = tmp_path / "model_sources.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            _cmd_sources(_make_args(tmp_path, out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["merged_sha256"] == "e" * 64

    def test_sources_creates_parent_dir(self, tmp_path: Path) -> None:
        """出力先の親ディレクトリが自動作成される。"""
        _make_manifest(tmp_path)
        out = tmp_path / "deep" / "nested" / "model_sources.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            _cmd_sources(_make_args(tmp_path, out))

        assert out.exists()

    def test_sources_missing_manifest_raises(self, tmp_path: Path) -> None:
        """manifest.json がない場合は FileNotFoundError。"""
        out = tmp_path / "model_sources.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            with pytest.raises(FileNotFoundError, match="manifest.json"):
                _cmd_sources(_make_args(tmp_path, out))

    def test_sources_subprocess_called_with_git_rev_parse(self, tmp_path: Path) -> None:
        """subprocess.run が git rev-parse HEAD を呼び出す。"""
        _make_manifest(tmp_path)
        out = tmp_path / "model_sources.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            _cmd_sources(_make_args(tmp_path, out))

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd == ["git", "rev-parse", "HEAD"]

    def test_sources_sparse_paths_contains_assets_models(self, tmp_path: Path) -> None:
        """sparse_paths に assets/models/ruri-v3-310m が含まれる。"""
        _make_manifest(tmp_path)
        out = tmp_path / "model_sources.json"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = _FAKE_SHA + "\n"
            _cmd_sources(_make_args(tmp_path, out))

        data = json.loads(out.read_text(encoding="utf-8"))
        assert "assets/models/ruri-v3-310m" in data["sparse_paths"]
