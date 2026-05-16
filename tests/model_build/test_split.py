"""split モジュールのユニットテスト（ネットワーク不要）。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from model_build.split import CHUNK_SIZE, sha256_file, split


def _make_fake_onnx(size: int) -> bytes:
    """テスト用の疑似 ONNX バイト列を生成する。"""
    return bytes(range(256)) * (size // 256) + bytes(range(size % 256))


@pytest.fixture()
def fake_model_onnx(tmp_path: Path) -> Path:
    """45MB 超の疑似 ONNX ファイルを作成する。"""
    data = _make_fake_onnx(CHUNK_SIZE + 1024)
    p = tmp_path / "model.onnx"
    p.write_bytes(data)
    return p


@pytest.fixture()
def fake_aux(tmp_path: Path) -> tuple[Path, Path]:
    """疑似 tokenizer.json と config.json を作成する。"""
    tok = tmp_path / "tokenizer.json"
    cfg = tmp_path / "config.json"
    tok.write_text('{"type": "fake"}', encoding="utf-8")
    cfg.write_text('{"hidden_size": 1024}', encoding="utf-8")
    return tok, cfg


class TestSha256File:
    """sha256_file のテスト。"""

    def test_known_content(self, tmp_path: Path) -> None:
        """既知のバイト列の SHA256 が一致する。"""
        data = b"hello"
        p = tmp_path / "f.bin"
        p.write_bytes(data)
        assert sha256_file(p) == hashlib.sha256(data).hexdigest()

    def test_large_file_chunked(self, tmp_path: Path) -> None:
        """大きなファイル（1MB 超）でも正しいハッシュを返す。"""
        data = b"x" * (2 * 1024 * 1024)
        p = tmp_path / "large.bin"
        p.write_bytes(data)
        assert sha256_file(p) == hashlib.sha256(data).hexdigest()


class TestSplit:
    """split 関数のテスト。"""

    def test_creates_parts_and_manifest(
        self, tmp_path: Path, fake_model_onnx: Path, fake_aux: tuple[Path, Path]
    ) -> None:
        """分割ファイルと manifest.json が生成される。"""
        tok, cfg = fake_aux
        out_dir = tmp_path / "out"
        manifest_path = split(
            model_onnx=fake_model_onnx,
            tokenizer_json=tok,
            config_json=cfg,
            output_dir=out_dir,
            model_name="test/model",
            hf_revision="a" * 40,
            quant="fp32",
        )
        assert manifest_path.exists()
        assert (out_dir / "tokenizer.json").exists()
        assert (out_dir / "config.json").exists()

    def test_part_count(
        self, tmp_path: Path, fake_model_onnx: Path, fake_aux: tuple[Path, Path]
    ) -> None:
        """CHUNK_SIZE + 1024 バイトなら 2 パートに分割される。"""
        tok, cfg = fake_aux
        out_dir = tmp_path / "out"
        split(
            model_onnx=fake_model_onnx,
            tokenizer_json=tok,
            config_json=cfg,
            output_dir=out_dir,
            model_name="test/model",
            hf_revision="b" * 40,
            quant="fp32",
        )
        parts = sorted(out_dir.glob("model.onnx.part*"))
        assert len(parts) == 2

    def test_manifest_sha256_correct(
        self, tmp_path: Path, fake_model_onnx: Path, fake_aux: tuple[Path, Path]
    ) -> None:
        """manifest の merged_sha256 が元ファイルの SHA256 と一致する。"""
        tok, cfg = fake_aux
        out_dir = tmp_path / "out"
        manifest_path = split(
            model_onnx=fake_model_onnx,
            tokenizer_json=tok,
            config_json=cfg,
            output_dir=out_dir,
            model_name="test/model",
            hf_revision="c" * 40,
            quant="fp16",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = sha256_file(fake_model_onnx)
        assert manifest["merged_sha256"] == expected

    def test_manifest_part_sha256_correct(
        self, tmp_path: Path, fake_model_onnx: Path, fake_aux: tuple[Path, Path]
    ) -> None:
        """manifest 内の各 part の SHA256 が実ファイルと一致する。"""
        tok, cfg = fake_aux
        out_dir = tmp_path / "out"
        manifest_path = split(
            model_onnx=fake_model_onnx,
            tokenizer_json=tok,
            config_json=cfg,
            output_dir=out_dir,
            model_name="test/model",
            hf_revision="d" * 40,
            quant="fp32",
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for part_info in manifest["parts"]:
            actual = sha256_file(out_dir / part_info["name"])
            assert actual == part_info["sha256"]

    def test_old_parts_deleted_on_rebuild(
        self, tmp_path: Path, fake_model_onnx: Path, fake_aux: tuple[Path, Path]
    ) -> None:
        """再実行時に古い part ファイルが削除される。"""
        tok, cfg = fake_aux
        out_dir = tmp_path / "out"
        kwargs = {
            "model_onnx": fake_model_onnx,
            "tokenizer_json": tok,
            "config_json": cfg,
            "output_dir": out_dir,
            "model_name": "test/model",
            "hf_revision": "e" * 40,
            "quant": "fp32",
        }
        split(**kwargs)
        first_parts = sorted(p.name for p in out_dir.glob("model.onnx.part*"))

        # 小さいファイルで再分割（part 数が変わるはず）
        small = tmp_path / "small.onnx"
        small.write_bytes(b"x" * 100)
        kwargs["model_onnx"] = small
        split(**kwargs)
        second_parts = sorted(p.name for p in out_dir.glob("model.onnx.part*"))

        assert len(second_parts) == 1
        assert first_parts != second_parts or len(first_parts) == 1

    def test_zero_byte_model_raises(self, tmp_path: Path, fake_aux: tuple[Path, Path]) -> None:
        """0 バイトの model.onnx は ValueError を送出する。"""
        tok, cfg = fake_aux
        zero_onnx = tmp_path / "model.onnx"
        zero_onnx.write_bytes(b"")
        out_dir = tmp_path / "out"
        with pytest.raises(ValueError, match="0 バイト"):
            split(
                model_onnx=zero_onnx,
                tokenizer_json=tok,
                config_json=cfg,
                output_dir=out_dir,
                model_name="test/model",
                hf_revision="a" * 40,
                quant="fp32",
            )

    def test_manifest_fields(
        self, tmp_path: Path, fake_model_onnx: Path, fake_aux: tuple[Path, Path]
    ) -> None:
        """manifest に必須フィールドが含まれる。"""
        tok, cfg = fake_aux
        out_dir = tmp_path / "out"
        manifest_path = split(
            model_onnx=fake_model_onnx,
            tokenizer_json=tok,
            config_json=cfg,
            output_dir=out_dir,
            model_name="test/model",
            hf_revision="f" * 40,
            quant="int8",
            embedding_dim=768,
            tokenizer_max_length=512,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("model_name", "hf_revision", "quantization", "embedding_dim",
                    "tokenizer_max_length", "merged_sha256", "parts",
                    "auxiliary_files", "created_at", "tool_version"):
            assert key in manifest, f"manifest にキー '{key}' が存在しない"
        assert manifest["embedding_dim"] == 768
        assert manifest["quantization"] == "int8"
