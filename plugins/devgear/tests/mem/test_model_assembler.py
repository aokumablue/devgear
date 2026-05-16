"""model_assembler のユニットテスト（ネットワーク不要）。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devgear.mem._paths import safe_join as _safe_join
from devgear.mem._paths import validate_sha256_format as _validate_sha256_format
from devgear.mem.model_assembler import (
    _copy_auxiliary,
    _is_already_assembled,
    _load_sources_spec,
    _make_git_env,
    _mean_pool_l2,
    _merge_and_verify,
    _sanity_inference,
    _sparse_checkout,
    _validate_git_commit,
    _validate_remote,
    _validate_sparse_path,
    _verify_parts,
    _verify_signed_tag,
    assemble,
)

# ── ヘルパー ──────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_parts(model_src: Path, parts_data: list[bytes]) -> list[dict]:
    """model_src に part ファイルを作成し、parts spec を返す。"""
    parts = []
    for i, data in enumerate(parts_data):
        name = f"model.onnx.part{i:02d}"
        (model_src / name).write_bytes(data)
        parts.append({"name": name, "sha256": _sha256(data)})
    return parts


def _make_spec(
    model_src: Path,
    parts_data: list[bytes],
    *,
    aux_files: dict[str, bytes] | None = None,
) -> dict:
    """テスト用 spec dict を生成する。aux_files: {name: bytes}"""
    parts = _make_parts(model_src, parts_data)
    merged = b"".join(parts_data)
    merged_sha = _sha256(merged)

    aux_files = aux_files or {
        "tokenizer.json": b'{"type":"fake"}',
        "config.json": b'{"dim":768}',
    }
    aux_specs = []
    for name, data in aux_files.items():
        (model_src / name).write_bytes(data)
        aux_specs.append({"name": name, "sha256": _sha256(data)})

    # manifest.json も配置（コピー元）
    manifest_data = json.dumps({"quantization": "fp16"}).encode()
    (model_src / "manifest.json").write_bytes(manifest_data)

    return {
        "schema_version": 1,
        "model_name": "cl-nagoya/ruri-v3-310m",
        "git_remote": "git@github.com:example/repo.git",
        "git_commit": "a" * 40,
        "signed_tag": "models/aaaaaaa-fp16",
        "signer_key_fingerprint": "A" * 40,
        "sparse_paths": ["assets/models"],
        "merged_sha256": merged_sha,
        "parts": parts,
        "auxiliary_files": aux_specs,
    }


# ── _make_git_env ─────────────────────────────────────────────────────────────

class TestMakeGitEnv:
    """_make_git_env のテスト。"""

    def test_gnupghome_set_when_trust_dir_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """~/.devgear/trust/gnupg が存在するとき GNUPGHOME が設定される。"""
        trust_gnupg = tmp_path / ".devgear" / "trust" / "gnupg"
        trust_gnupg.mkdir(parents=True)
        # Path.home() を tmp_path にモンキーパッチする
        monkeypatch.setattr("devgear.mem.model_assembler.Path.home", lambda: tmp_path)
        env = _make_git_env()
        assert env.get("GNUPGHOME") == str(trust_gnupg)

    def test_gnupghome_not_set_when_trust_dir_absent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """~/.devgear/trust/gnupg が存在しないとき GNUPGHOME は設定されない。"""
        monkeypatch.setattr("devgear.mem.model_assembler.Path.home", lambda: tmp_path)
        env = _make_git_env()
        assert "GNUPGHOME" not in env


# ── _validate_remote ──────────────────────────────────────────────────────────

class TestValidateRemote:
    """_validate_remote の許可リスト検証テスト（Table-driven）。"""

    @pytest.mark.parametrize("remote,expected_ok", [
        ("git@github.com:aokumablue/devgear.git", True),
        ("git@github.com:org/repo-name.git", True),
        ("https://github.com/x/y.git", False),
        ("git@evil.example.com:x/y.git", False),
        ("ext::sh -c rm -rf /", False),
        ("file:///etc/passwd", False),
        ("", False),
    ])
    def test_validate_remote(self, remote: str, expected_ok: bool) -> None:
        """許可リスト外は ValueError。"""
        if expected_ok:
            _validate_remote(remote)  # 例外なし
        else:
            with pytest.raises(ValueError, match="許可されていない"):
                _validate_remote(remote)


# ── _validate_git_commit ──────────────────────────────────────────────────────

class TestValidateGitCommit:
    """_validate_git_commit の Table-driven テスト。"""

    @pytest.mark.parametrize("commit,expected_ok", [
        ("a" * 40, True),
        ("a" * 64, True),
        ("a" * 39, False),
        ("a" * 41, False),
        ("g" * 40, False),
        ("", False),
    ])
    def test_validate_git_commit(self, commit: str, expected_ok: bool) -> None:
        """40 桁 / 64 桁 hex のみ受理。"""
        if expected_ok:
            _validate_git_commit(commit)
        else:
            with pytest.raises(ValueError, match="git commit"):
                _validate_git_commit(commit)


# ── _validate_sparse_path ─────────────────────────────────────────────────────

class TestValidateSparsePath:
    """_validate_sparse_path の Table-driven テスト。"""

    @pytest.mark.parametrize("path,expected_ok", [
        ("assets/models", True),
        ("--upload-pack=evil", False),
        ("../outside", False),
        ("/etc/passwd", False),
        ("a/../b", False),
        ("ok/path", True),
    ])
    def test_validate_sparse_path(self, path: str, expected_ok: bool) -> None:
        """オプション偽装・パストラバーサル・絶対パスを拒否。"""
        if expected_ok:
            _validate_sparse_path(path)
        else:
            with pytest.raises(ValueError):
                _validate_sparse_path(path)


# ── _mean_pool_l2 ─────────────────────────────────────────────────────────────

class TestMeanPoolL2:
    """_mean_pool_l2 の Table-driven テスト。"""

    @pytest.mark.parametrize("desc,vec_factory,expected_norm_approx", [
        ("単位ベクトル → norm=1", lambda np: _unit_vec(np), 1.0),
        ("全ゼロ+clip → norm≈0", lambda np: _zero_vec(np), 0.0),
        ("均一ベクトル → norm=1", lambda np: _uniform_vec(np), 1.0),
    ])
    def test_output_shape_and_norm(self, desc: str, vec_factory, expected_norm_approx: float) -> None:
        """mean pooling + L2 正規化後の形状とノルムを確認。"""
        import math

        import numpy as np

        token_embs, attention_mask = vec_factory(np)
        result = _mean_pool_l2(token_embs, attention_mask)
        assert result.shape == (1, token_embs.shape[2]), f"{desc}: shape 不正"
        norm = math.sqrt(float(np.dot(result[0], result[0])))
        assert abs(norm - expected_norm_approx) < 1e-3, f"{desc}: norm={norm:.6f}"


def _unit_vec(np):
    vec = np.zeros((1, 3, 4), dtype=np.float32)
    vec[0, 0, 0] = 1.0
    mask = np.array([[1, 1, 1]], dtype=np.int64)
    return vec, mask


def _zero_vec(np):
    vec = np.zeros((1, 3, 4), dtype=np.float32)
    mask = np.array([[1, 1, 1]], dtype=np.int64)
    return vec, mask


def _uniform_vec(np):
    vec = np.ones((1, 3, 4), dtype=np.float32)
    mask = np.array([[1, 1, 1]], dtype=np.int64)
    return vec, mask


# ── _validate_sha256_format ────────────────────────────────────────────────────

class TestValidateSha256Format:
    """_validate_sha256_format のテスト（Table-driven）。"""

    @pytest.mark.parametrize("value,expected_ok", [
        ("a" * 64, True),
        ("a" * 63, False),
        ("a" * 65, False),
        ("g" * 64, False),
        ("", False),
    ])
    def test_validate(self, value: str, expected_ok: bool) -> None:
        """64 文字の hex のみ受理。"""
        if expected_ok:
            _validate_sha256_format(value, "test")
        else:
            with pytest.raises(ValueError, match="不正な SHA256"):
                _validate_sha256_format(value, "test")


# ── _safe_join ────────────────────────────────────────────────────────────────

class TestSafeJoin:
    """_safe_join のテスト（Table-driven）。"""

    @pytest.mark.parametrize("name,expected_ok", [
        ("subdir/file.txt", True),
        ("file.txt", True),
        ("../outside.txt", False),
    ])
    def test_safe_join(self, tmp_path: Path, name: str, expected_ok: bool) -> None:
        """base 外へのトラバーサルは ValueError。"""
        if expected_ok:
            result = _safe_join(tmp_path, name)
            assert str(result).startswith(str(tmp_path))
        else:
            with pytest.raises(ValueError, match="不正なパス"):
                _safe_join(tmp_path, name)


# ── _is_already_assembled ─────────────────────────────────────────────────────

class TestIsAlreadyAssembled:
    """_is_already_assembled のテスト（Table-driven）。"""

    @pytest.mark.parametrize("setup,expected", [
        ("no_model", False),
        ("sha_match", True),
        ("sha_differ", False),
        ("invalid_sha", False),
    ])
    def test_is_assembled(self, tmp_path: Path, setup: str, expected: bool) -> None:
        """model.onnx の有無と SHA 一致状況で真偽値を返す。"""
        spec: dict
        if setup == "no_model":
            spec = {"merged_sha256": "a" * 64}
        elif setup == "sha_match":
            data = b"model-data"
            (tmp_path / "model.onnx").write_bytes(data)
            spec = {"merged_sha256": _sha256(data)}
        elif setup == "sha_differ":
            (tmp_path / "model.onnx").write_bytes(b"model-data")
            spec = {"merged_sha256": "b" * 64}
        else:  # invalid_sha
            (tmp_path / "model.onnx").write_bytes(b"x")
            spec = {"merged_sha256": "invalid"}
        assert _is_already_assembled(tmp_path, spec) is expected


# ── _load_sources_spec ────────────────────────────────────────────────────────

class TestLoadSourcesSpec:
    """_load_sources_spec のスキーマ検証テスト（Table-driven）。"""

    def _base_spec(self) -> dict:
        return {
            "schema_version": 1,
            "git_remote": "git@github.com:aokumablue/devgear.git",
            "git_commit": "a" * 40,
            "signed_tag": "models/aaaaaaa-fp16",
            "signer_key_fingerprint": "A" * 40,
            "sparse_paths": ["assets/models"],
            "merged_sha256": "a" * 64,
            "parts": [{"name": "model.onnx.part00", "sha256": "a" * 64}],
            "auxiliary_files": [{"name": "tokenizer.json", "sha256": "a" * 64}],
        }

    @pytest.mark.parametrize("missing_key", [
        "schema_version", "git_remote", "git_commit", "sparse_paths",
        "merged_sha256", "parts", "auxiliary_files",
        "signed_tag", "signer_key_fingerprint",
    ])
    def test_missing_required_key_raises(self, tmp_path: Path, missing_key: str) -> None:
        """必須キーが欠落すると ValueError。"""
        spec = self._base_spec()
        del spec[missing_key]
        f = tmp_path / "model_sources.json"
        f.write_text(json.dumps(spec))
        with pytest.raises(ValueError, match=missing_key):
            _load_sources_spec(f)

    def test_unsupported_schema_version_raises(self, tmp_path: Path) -> None:
        """schema_version != 1 は ValueError。"""
        spec = self._base_spec()
        spec["schema_version"] = 99
        f = tmp_path / "model_sources.json"
        f.write_text(json.dumps(spec))
        with pytest.raises(ValueError, match="schema_version"):
            _load_sources_spec(f)

    def test_empty_parts_raises(self, tmp_path: Path) -> None:
        """parts が空配列は ValueError。"""
        spec = self._base_spec()
        spec["parts"] = []
        f = tmp_path / "model_sources.json"
        f.write_text(json.dumps(spec))
        with pytest.raises(ValueError, match="parts"):
            _load_sources_spec(f)

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        """ファイルが存在しない場合は FileNotFoundError。"""
        with pytest.raises(FileNotFoundError, match="model_sources.json"):
            _load_sources_spec(tmp_path / "no_such.json")

    def test_empty_sparse_paths_raises(self, tmp_path: Path) -> None:
        """sparse_paths が空配列は ValueError。"""
        spec = self._base_spec()
        spec["sparse_paths"] = []
        f = tmp_path / "model_sources.json"
        f.write_text(json.dumps(spec))
        with pytest.raises(ValueError, match="sparse_paths"):
            _load_sources_spec(f)

    def test_valid_spec_returns_dict(self, tmp_path: Path) -> None:
        """正常な spec は dict を返す。"""
        spec = self._base_spec()
        f = tmp_path / "model_sources.json"
        f.write_text(json.dumps(spec))
        result = _load_sources_spec(f)
        assert result["schema_version"] == 1

    @pytest.mark.parametrize("invalid_tag", [
        "invalid-tag",
        "models/aaaaaaa",
        "models/aaaaaaa-invalid_quant",
        "refs/tags/models/aaaaaaa-fp16",
    ])
    def test_invalid_signed_tag_format_raises(self, tmp_path: Path, invalid_tag: str) -> None:
        """signed_tag の形式が不正なら ValueError。"""
        spec = self._base_spec()
        spec["signed_tag"] = invalid_tag
        f = tmp_path / "model_sources.json"
        f.write_text(json.dumps(spec))
        with pytest.raises(ValueError, match="signed_tag"):
            _load_sources_spec(f)

    @pytest.mark.parametrize("invalid_fp", [
        "abc",
        "a" * 40,        # 小文字（大文字のみ有効）
        "Z" * 40,        # 非 hex 文字
        "A" * 39,        # 39 桁
        "A" * 41,        # 41 桁
    ])
    def test_invalid_fingerprint_format_raises(self, tmp_path: Path, invalid_fp: str) -> None:
        """signer_key_fingerprint の形式が不正なら ValueError。"""
        spec = self._base_spec()
        spec["signer_key_fingerprint"] = invalid_fp
        f = tmp_path / "model_sources.json"
        f.write_text(json.dumps(spec))
        with pytest.raises(ValueError, match="signer_key_fingerprint"):
            _load_sources_spec(f)


# ── _verify_parts ─────────────────────────────────────────────────────────────

class TestVerifyParts:
    """_verify_parts のテスト。"""

    def _make_assets_dir(self, tmp_path: Path, parts_data: list[bytes]) -> tuple[Path, dict]:
        """tmp_path に sparse 構造を作り (assets_dir, spec) を返す。"""
        sparse_rel = "assets/models"
        model_src = tmp_path / sparse_rel
        model_src.mkdir(parents=True)
        spec = _make_spec(model_src, parts_data)
        return tmp_path, spec

    def test_valid_parts_no_error(self, tmp_path: Path) -> None:
        """SHA が正しい part は例外なし。"""
        assets_dir, spec = self._make_assets_dir(tmp_path, [b"part0", b"part1"])
        _verify_parts(assets_dir, spec)

    def test_sha_mismatch_raises(self, tmp_path: Path) -> None:
        """SHA 不一致は ValueError。"""
        assets_dir, spec = self._make_assets_dir(tmp_path, [b"part0"])
        # part を改竄
        sparse_rel = spec["sparse_paths"][0]
        (assets_dir / sparse_rel / "model.onnx.part00").write_bytes(b"tampered")
        with pytest.raises(ValueError, match="SHA256 不一致"):
            _verify_parts(assets_dir, spec)

    def test_missing_part_raises(self, tmp_path: Path) -> None:
        """part が欠落している場合は FileNotFoundError。"""
        assets_dir, spec = self._make_assets_dir(tmp_path, [b"part0"])
        sparse_rel = spec["sparse_paths"][0]
        (assets_dir / sparse_rel / "model.onnx.part00").unlink()
        with pytest.raises(FileNotFoundError, match="part が見つかりません"):
            _verify_parts(assets_dir, spec)

    def test_wrong_prefix_raises(self, tmp_path: Path) -> None:
        """model.onnx.part プレフィックスでない名前は ValueError。"""
        assets_dir, spec = self._make_assets_dir(tmp_path, [b"data"])
        spec["parts"][0]["name"] = "evil.onnx.part00"
        with pytest.raises(ValueError, match="名前が不正"):
            _verify_parts(assets_dir, spec)

    def test_non_numeric_index_raises(self, tmp_path: Path) -> None:
        """インデックスが数値でない場合は ValueError。"""
        assets_dir, spec = self._make_assets_dir(tmp_path, [b"data"])
        spec["parts"][0]["name"] = "model.onnx.partAB"
        with pytest.raises(ValueError, match="数値でない"):
            _verify_parts(assets_dir, spec)

    def test_out_of_order_parts_raises(self, tmp_path: Path) -> None:
        """parts が単調増加でない（part01,part00 の順）は ValueError。"""
        assets_dir, spec = self._make_assets_dir(tmp_path, [b"p0", b"p1"])
        # 順序を入れ替え
        spec["parts"] = list(reversed(spec["parts"]))
        with pytest.raises(ValueError, match="順序が不正"):
            _verify_parts(assets_dir, spec)


# ── _merge_and_verify ─────────────────────────────────────────────────────────

class TestMergeAndVerify:
    """_merge_and_verify のテスト。"""

    def _setup(self, tmp_path: Path, parts_data: list[bytes]) -> tuple[Path, Path, dict]:
        """assets_dir と target_dir を作り (assets_dir, target_dir, spec) を返す。"""
        sparse_rel = "assets/models"
        model_src = tmp_path / "repo" / sparse_rel
        model_src.mkdir(parents=True)
        spec = _make_spec(model_src, parts_data)
        target = tmp_path / "target"
        return tmp_path / "repo", target, spec

    def test_merge_creates_model_onnx(self, tmp_path: Path) -> None:
        """統合後 model.onnx が target_dir に作成される。"""
        assets_dir, target_dir, spec = self._setup(tmp_path, [b"abc", b"def"])
        _merge_and_verify(assets_dir, target_dir, spec)
        assert (target_dir / "model.onnx").exists()

    def test_merged_content_correct(self, tmp_path: Path) -> None:
        """統合後ファイルの内容が正しい。"""
        parts = [b"hello", b"world"]
        assets_dir, target_dir, spec = self._setup(tmp_path, parts)
        _merge_and_verify(assets_dir, target_dir, spec)
        content = (target_dir / "model.onnx").read_bytes()
        assert content == b"helloworld"

    def test_sha_mismatch_removes_tmp(self, tmp_path: Path) -> None:
        """merged SHA 不一致なら ValueError かつ tmp が削除される。"""
        assets_dir, target_dir, spec = self._setup(tmp_path, [b"data"])
        spec["merged_sha256"] = "f" * 64  # 不正な SHA
        target_dir.mkdir(parents=True)
        with pytest.raises(ValueError, match="SHA256 不一致"):
            _merge_and_verify(assets_dir, target_dir, spec)
        # 中間ファイルが残っていないことを確認
        assert not (target_dir / "model.onnx.tmp").exists()

    def test_target_dir_created_with_0o700(self, tmp_path: Path) -> None:
        """target_dir が 0o700 で作成される。"""
        assets_dir, target_dir, spec = self._setup(tmp_path, [b"x"])
        _merge_and_verify(assets_dir, target_dir, spec)
        mode = oct(os.stat(target_dir).st_mode & 0o777)
        assert mode == oct(0o700)

    def test_symlink_target_dir_raises(self, tmp_path: Path) -> None:
        """target_dir がシンボリックリンクの場合は ValueError。"""
        assets_dir, target_dir, spec = self._setup(tmp_path, [b"x"])
        real_dir = tmp_path / "real_target"
        real_dir.mkdir()
        target_dir.symlink_to(real_dir)
        with pytest.raises(ValueError, match="シンボリックリンク"):
            _merge_and_verify(assets_dir, target_dir, spec)


# ── _copy_auxiliary ──────────────────────────────────────────────────────────

class TestCopyAuxiliary:
    """_copy_auxiliary のテスト。"""

    def _setup(self, tmp_path: Path) -> tuple[Path, Path, dict]:
        """assets_dir と target_dir を作り (assets_dir, target_dir, spec) を返す。"""
        sparse_rel = "assets/models"
        model_src = tmp_path / "repo" / sparse_rel
        model_src.mkdir(parents=True)
        spec = _make_spec(model_src, [b"x"])
        target = tmp_path / "target"
        target.mkdir()
        return tmp_path / "repo", target, spec

    def test_tokenizer_json_copied(self, tmp_path: Path) -> None:
        """tokenizer.json がコピーされる。"""
        assets_dir, target_dir, spec = self._setup(tmp_path)
        _copy_auxiliary(assets_dir, target_dir, spec)
        assert (target_dir / "tokenizer.json").exists()

    def test_config_json_copied(self, tmp_path: Path) -> None:
        """config.json がコピーされる。"""
        assets_dir, target_dir, spec = self._setup(tmp_path)
        _copy_auxiliary(assets_dir, target_dir, spec)
        assert (target_dir / "config.json").exists()

    def test_manifest_json_copied(self, tmp_path: Path) -> None:
        """manifest.json がコピーされる。"""
        assets_dir, target_dir, spec = self._setup(tmp_path)
        _copy_auxiliary(assets_dir, target_dir, spec)
        assert (target_dir / "manifest.json").exists()

    def test_sha_mismatch_raises(self, tmp_path: Path) -> None:
        """auxiliary file の SHA 不一致は ValueError。"""
        assets_dir, target_dir, spec = self._setup(tmp_path)
        # tokenizer.json の SHA を破損させる
        spec["auxiliary_files"][0]["sha256"] = "f" * 64
        with pytest.raises(ValueError, match="SHA256 不一致"):
            _copy_auxiliary(assets_dir, target_dir, spec)

    def test_missing_manifest_raises(self, tmp_path: Path) -> None:
        """manifest.json がない場合は FileNotFoundError。"""
        assets_dir, target_dir, spec = self._setup(tmp_path)
        sparse_rel = spec["sparse_paths"][0]
        (assets_dir / sparse_rel / "manifest.json").unlink()
        with pytest.raises(FileNotFoundError, match="manifest.json"):
            _copy_auxiliary(assets_dir, target_dir, spec)

    def test_missing_tokenizer_skips_with_warning(self, tmp_path: Path) -> None:
        """tokenizer.json がない場合は警告ログを出してスキップ（エラーにならない）。"""
        assets_dir, target_dir, spec = self._setup(tmp_path)
        sparse_rel = spec["sparse_paths"][0]
        (assets_dir / sparse_rel / "tokenizer.json").unlink()
        # 例外なく完了する
        _copy_auxiliary(assets_dir, target_dir, spec)
        assert not (target_dir / "tokenizer.json").exists()


# ── _sparse_checkout（subprocess モック）────────────────────────────────────

class TestSparseCheckout:
    """_sparse_checkout の subprocess 呼び出しをモックして検証する。"""

    # _verify_signed_tag をスキップするために署名検証を無効化する
    @pytest.fixture(autouse=True)
    def skip_signature_verify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """各テストで署名検証をスキップする（git tag 署名検証は TestVerifySignedTag で個別にテスト）。"""
        monkeypatch.setenv("DEVGEAR_SKIP_SIGNATURE_VERIFY", "1")

    def _base_spec(self) -> dict:
        return {
            "git_remote": "git@github.com:aokumablue/devgear.git",
            "git_commit": "a" * 40,
            "signed_tag": "models/aaaaaaa-fp16",
            "signer_key_fingerprint": "A" * 40,
            "sparse_paths": ["assets/models"],
        }

    def test_calls_git_clone(self, tmp_path: Path) -> None:
        """subprocess.run が git clone を呼び出す。"""
        spec = self._base_spec()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _sparse_checkout(spec, tmp_path)

        first_call = mock_run.call_args_list[0]
        cmd = first_call[0][0]
        assert cmd[0] == "git"
        assert "clone" in cmd
        assert "git@github.com:aokumablue/devgear.git" in cmd

    def test_protocol_allowlist_in_argv(self, tmp_path: Path) -> None:
        """全 git 呼び出しに protocol.ext.allow=never が含まれる。"""
        spec = self._base_spec()

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _sparse_checkout(spec, tmp_path)

        for call in mock_run.call_args_list:
            cmd = call[0][0]
            assert "protocol.ext.allow=never" in cmd, f"安全フラグ未付与: {cmd}"

    def test_invalid_remote_raises(self, tmp_path: Path) -> None:
        """許可リスト外の git_remote は ValueError。"""
        spec = self._base_spec()
        spec["git_remote"] = "https://evil.example.com/repo.git"
        with pytest.raises(ValueError, match="許可されていない"):
            _sparse_checkout(spec, tmp_path)

    def test_uses_env_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEVGEAR_TESTING=1 のとき DEVGEAR_MODEL_REMOTE が優先される。"""
        spec = self._base_spec()
        spec["git_commit"] = "b" * 40
        override = "git@github.com:aokumablue/override.git"

        monkeypatch.setenv("DEVGEAR_TESTING", "1")
        monkeypatch.delenv("DEVGEAR_MODEL_REMOTE", raising=False)
        monkeypatch.setenv("DEVGEAR_MODEL_REMOTE", override)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _sparse_checkout(spec, tmp_path)

        first_call = mock_run.call_args_list[0]
        cmd = first_call[0][0]
        assert override in cmd
        assert "git@github.com:aokumablue/devgear.git" not in cmd

    def test_env_override_ignored_without_testing_flag(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEVGEAR_TESTING=1 なしでは DEVGEAR_MODEL_REMOTE が無視され spec の remote が使われる。"""
        spec = self._base_spec()
        spec["git_commit"] = "b" * 40
        override = "git@github.com:aokumablue/override.git"

        monkeypatch.delenv("DEVGEAR_TESTING", raising=False)
        monkeypatch.setenv("DEVGEAR_MODEL_REMOTE", override)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            _sparse_checkout(spec, tmp_path)

        first_call = mock_run.call_args_list[0]
        cmd = first_call[0][0]
        assert "git@github.com:aokumablue/devgear.git" in cmd
        assert override not in cmd

    def test_invalid_env_override_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEVGEAR_TESTING=1 時に許可リスト外の DEVGEAR_MODEL_REMOTE は ValueError。"""
        spec = self._base_spec()
        monkeypatch.setenv("DEVGEAR_TESTING", "1")
        monkeypatch.delenv("DEVGEAR_MODEL_REMOTE", raising=False)
        monkeypatch.setenv("DEVGEAR_MODEL_REMOTE", "ext::sh -c 'echo PWN'")

        with pytest.raises(ValueError, match="許可されていない"):
            _sparse_checkout(spec, tmp_path)

    def test_git_failure_logs_and_reraises(self, tmp_path: Path) -> None:
        """git コマンド失敗時に stderr をログに出力し CalledProcessError を再 raise する。"""
        import subprocess

        spec = self._base_spec()

        err = subprocess.CalledProcessError(1, ["git"], stderr=b"fatal: repository not found")
        with patch("subprocess.run", side_effect=err):
            with pytest.raises(subprocess.CalledProcessError):
                _sparse_checkout(spec, tmp_path)


# ── _verify_signed_tag ───────────────────────────────────────────────────────

class TestVerifySignedTag:
    """_verify_signed_tag の git 署名検証テスト（subprocess モック）。"""

    def _base_spec(self) -> dict:
        return {
            "signed_tag": "models/aaaaaaa-fp16",
            "signer_key_fingerprint": "A" * 40,
            "git_commit": "a" * 40,
        }

    def _make_git_env(self) -> dict:
        return {}

    def _validsig_stderr(self, fp: str, commit: str) -> bytes:
        """git verify-tag --raw 成功時の stderr 形式を模倣する。"""
        return (
            f"[GNUPG:] GOODSIG DEADBEEF Maintainer <key@example.com>\n"
            f"[GNUPG:] VALIDSIG {fp} 2024-01-01 1234567890\n"
            f"[GNUPG:] TRUST_ULTIMATE 0 pgp\n"
        ).encode()

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """VALIDSIG + 指紋一致 + commit 一致 → 例外なし。"""
        spec = self._base_spec()
        fp = "A" * 40
        commit = "a" * 40

        with patch("subprocess.run") as mock_run:
            # fetch
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=b"", stdout=b""),  # fetch
                MagicMock(returncode=0, stderr=self._validsig_stderr(fp, commit), stdout=b""),  # verify-tag
                MagicMock(returncode=0, stderr=b"", stdout=(commit + "\n").encode()),  # rev-list
            ]
            _verify_signed_tag(spec, "/fake/clone", self._make_git_env())

    def test_unsigned_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """verify-tag 戻り値非 0 → ValueError("tag 署名検証失敗")。"""
        spec = self._base_spec()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=b"", stdout=b""),  # fetch
                MagicMock(returncode=1, stderr=b"error: not signed", stdout=b""),  # verify-tag
            ]
            with pytest.raises(ValueError, match="tag 署名検証失敗"):
                _verify_signed_tag(spec, "/fake/clone", self._make_git_env())

    def test_no_validsig_line_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """verify-tag が成功するが VALIDSIG 行なし → ValueError("鍵指紋を抽出できません")。"""
        spec = self._base_spec()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=b"", stdout=b""),  # fetch
                MagicMock(returncode=0, stderr=b"[GNUPG:] GOODSIG\n", stdout=b""),  # verify-tag（VALIDSIG なし）
            ]
            with pytest.raises(ValueError, match="鍵指紋を抽出できません"):
                _verify_signed_tag(spec, "/fake/clone", self._make_git_env())

    def test_fingerprint_mismatch_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """VALIDSIG があるが指紋不一致 → ValueError("鍵指紋不一致")。"""
        spec = self._base_spec()
        wrong_fp = "B" * 40  # spec は "A" * 40

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=b"", stdout=b""),  # fetch
                MagicMock(returncode=0, stderr=self._validsig_stderr(wrong_fp, "a" * 40), stdout=b""),  # verify-tag
            ]
            with pytest.raises(ValueError, match="鍵指紋不一致"):
                _verify_signed_tag(spec, "/fake/clone", self._make_git_env())

    def test_commit_mismatch_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """指紋一致でも tag が指す commit が spec と異なる → ValueError("tag commit 不一致")。"""
        spec = self._base_spec()
        fp = "A" * 40
        wrong_commit = "b" * 40  # spec は "a" * 40

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stderr=b"", stdout=b""),  # fetch
                MagicMock(returncode=0, stderr=self._validsig_stderr(fp, "a" * 40), stdout=b""),  # verify-tag
                MagicMock(returncode=0, stderr=b"", stdout=(wrong_commit + "\n").encode()),  # rev-list
            ]
            with pytest.raises(ValueError, match="tag commit 不一致"):
                _verify_signed_tag(spec, "/fake/clone", self._make_git_env())

    def test_skip_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DEVGEAR_SKIP_SIGNATURE_VERIFY=1 で subprocess を呼ばずに return する。"""
        spec = self._base_spec()
        monkeypatch.setenv("DEVGEAR_SKIP_SIGNATURE_VERIFY", "1")

        with patch("subprocess.run") as mock_run:
            _verify_signed_tag(spec, "/fake/clone", self._make_git_env())
            mock_run.assert_not_called()


# ── _sanity_inference（ORT モック）──────────────────────────────────────────

class TestSanityInference:
    """_sanity_inference の ORT と tokenizers をモックして検証する。"""

    def _make_target(self, tmp_path: Path, dim: int = 768, norm_ok: bool = True) -> tuple[Path, MagicMock, MagicMock]:
        """target_dir に model.onnx / tokenizer.json を配置し、セッションモックを返す。"""
        target = tmp_path / "target"
        target.mkdir()
        (target / "model.onnx").write_bytes(b"fake")
        (target / "tokenizer.json").write_bytes(b'{}')

        import numpy as np

        # 単位ベクトル or ゼロベクトルを作る
        if norm_ok:
            vec = np.zeros((1, 1, dim), dtype=np.float32)
            vec[0, 0, 0] = 1.0  # mean pooling + 正規化後 norm=1
        else:
            vec = np.zeros((1, 1, dim), dtype=np.float32)  # ゼロベクトル → clip(min=1e-9) → 分母≈1e-9 → norm≈0

        mock_session = MagicMock()
        mock_session.run.return_value = [vec]
        mock_session.get_inputs.return_value = []  # token_type_ids なし

        mock_enc = MagicMock()
        mock_enc.ids = [1, 2, 3] + [0] * 509
        mock_enc.attention_mask = [1, 1, 1] + [0] * 509

        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.return_value = mock_enc

        return target, mock_session, mock_tokenizer

    def test_valid_embedding_no_error(self, tmp_path: Path) -> None:
        """dim=768, norm≈1.0 なら例外なし。"""
        target, mock_session, mock_tokenizer = self._make_target(tmp_path)

        with patch("onnxruntime.InferenceSession", return_value=mock_session), \
             patch("onnxruntime.SessionOptions"), \
             patch("tokenizers.Tokenizer.from_file", return_value=mock_tokenizer):
            _sanity_inference(target)

    def test_wrong_dim_raises(self, tmp_path: Path) -> None:
        """dim が 768 以外は ValueError。"""
        target, mock_session, mock_tokenizer = self._make_target(tmp_path, dim=512)

        with patch("onnxruntime.InferenceSession", return_value=mock_session), \
             patch("onnxruntime.SessionOptions"), \
             patch("tokenizers.Tokenizer.from_file", return_value=mock_tokenizer):
            with pytest.raises(ValueError, match="埋め込み次元"):
                _sanity_inference(target)

    def test_wrong_norm_raises(self, tmp_path: Path) -> None:
        """L2 ノルムが 1 から大幅に外れる場合は ValueError。"""
        target, mock_session, mock_tokenizer = self._make_target(tmp_path, norm_ok=False)

        with patch("onnxruntime.InferenceSession", return_value=mock_session), \
             patch("onnxruntime.SessionOptions"), \
             patch("tokenizers.Tokenizer.from_file", return_value=mock_tokenizer):
            with pytest.raises(ValueError, match="L2 ノルム"):
                _sanity_inference(target)

    def test_with_token_type_ids_input(self, tmp_path: Path) -> None:
        """token_type_ids 入力が必要なモデルでも例外なく動作する。"""
        target, mock_session, mock_tokenizer = self._make_target(tmp_path)

        class FakeInput:
            def __init__(self, name: str) -> None:
                self.name = name

        mock_session.get_inputs.return_value = [
            FakeInput("input_ids"),
            FakeInput("attention_mask"),
            FakeInput("token_type_ids"),
        ]

        with patch("onnxruntime.InferenceSession", return_value=mock_session), \
             patch("onnxruntime.SessionOptions"), \
             patch("tokenizers.Tokenizer.from_file", return_value=mock_tokenizer):
            _sanity_inference(target)


# ── assemble E2E（sparse_checkout をモック）──────────────────────────────────

class TestAssemble:
    """assemble() の E2E テスト（git は叩かない）。"""

    def _setup_sources(self, tmp_path: Path) -> tuple[Path, Path, dict]:
        """
        tmp_path/assets/models にファイルを配置し、
        model_sources.json を生成して (sources_json, target_dir, spec) を返す。
        """
        model_src = tmp_path / "assets" / "models"
        model_src.mkdir(parents=True)
        parts_data = [b"chunk0", b"chunk1"]
        spec = _make_spec(model_src, parts_data)

        sources_json = tmp_path / "model_sources.json"
        sources_json.write_text(json.dumps(spec), encoding="utf-8")

        target = tmp_path / "target"
        return sources_json, target, spec

    def _mock_sparse(self, assets_root: Path, spec: dict) -> Path:
        """_sparse_checkout の代わりに assets_root を返す関数。"""
        return assets_root

    def test_assemble_creates_model_onnx(self, tmp_path: Path) -> None:
        """assemble() が model.onnx を target に生成する。"""
        sources_json, target, _ = self._setup_sources(tmp_path)
        assets_root = tmp_path  # repo ルートとして使う

        import numpy as np
        vec = np.zeros((1, 1, 768), dtype=np.float32)
        vec[0, 0, 0] = 1.0

        mock_session = MagicMock()
        mock_session.run.return_value = [vec]
        mock_session.get_inputs.return_value = []

        mock_enc = MagicMock()
        mock_enc.ids = [1, 2, 3] + [0] * 509
        mock_enc.attention_mask = [1, 1, 1] + [0] * 509
        mock_tokenizer = MagicMock()
        mock_tokenizer.encode.return_value = mock_enc

        with patch("devgear.mem.model_assembler._sparse_checkout",
                   return_value=assets_root), \
             patch("onnxruntime.InferenceSession", return_value=mock_session), \
             patch("onnxruntime.SessionOptions"), \
             patch("tokenizers.Tokenizer.from_file", return_value=mock_tokenizer):
            assemble(sources_json, target)

        assert (target / "model.onnx").exists()

    def test_assemble_skips_when_already_assembled(self, tmp_path: Path) -> None:
        """SHA が一致する model.onnx が既にあれば sparse_checkout を呼ばない。"""
        sources_json, target, _ = self._setup_sources(tmp_path)

        # 既に統合済みにする
        merged = b"chunk0chunk1"
        target.mkdir()
        (target / "model.onnx").write_bytes(merged)

        with patch("devgear.mem.model_assembler._sparse_checkout") as mock_sc:
            assemble(sources_json, target)

        mock_sc.assert_not_called()
