"""モデル統合 — git sparse-checkout で分割 part を取得し ~/.devgear/models/ に統合する。

純標準ライブラリのみで動作する（hashlib, hmac, json, os, pathlib, shutil, subprocess, tempfile）。
onnxruntime / tokenizers は _sanity_inference のみで使用（install.sh 実行後に利用可能）。

CLI: python3 -m devgear.mem.model_assembler --sources <json> --target <dir>
"""

from __future__ import annotations

import argparse
import hmac
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from devgear.mem._paths import safe_join as _safe_join
from devgear.mem._paths import sha256_file as _sha256_path
from devgear.mem._paths import validate_sha256_format as _validate_sha256_format

log = logging.getLogger("MODEL_ASSEMBLER")

# git@github.com:<owner>/<repo>.git 形式のみ許可
_ALLOWED_REMOTE_RE = re.compile(r"^git@github\.com:[\w][\w.-]*/[\w][\w.-]*\.git$")

# protocol.ext / protocol.file 悪用を全 git 呼び出しで禁止
_GIT_SAFE_FLAGS = [
    "-c", "protocol.ext.allow=never",
    "-c", "protocol.file.allow=never",
]


def _make_git_env() -> dict:
    """呼び出し時の os.environ を元に git 安全環境変数マップを返す。

    モジュールロード時スナップショットを避けることでテスト時の環境変数差し替えに対応する。
    GIT_ASKPASS: /bin/true が存在すれば使用し、なければ shutil.which("true") でフォールバック。
    """
    import shutil

    askpass = "/bin/true"
    if not Path(askpass).exists():  # pragma: no cover
        found = shutil.which("true")
        askpass = found if found else askpass
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": askpass,
    }
    # ~/.devgear/trust/gnupg が存在すれば信頼鍵ストアとして指定する
    trust_gpg = Path.home() / ".devgear" / "trust" / "gnupg"
    if trust_gpg.exists():
        env["GNUPGHOME"] = str(trust_gpg)
    return env


def _validate_remote(remote: str) -> None:
    """git remote URL が許可リスト形式（git@github.com:<owner>/<repo>.git）に合致することを検証する。"""
    if not _ALLOWED_REMOTE_RE.match(remote):
        raise ValueError(f"許可されていない git remote 形式: '{remote[:64]}'")


def _validate_git_commit(value: str) -> None:
    """git commit が 40 桁または 64 桁の hex 文字列であることを検証する。"""
    if len(value) not in (40, 64):
        raise ValueError(f"不正な git commit 形式: '{value[:16]}...'")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"不正な git commit 形式: '{value[:16]}...'") from exc


def _validate_sparse_path(value: str) -> None:
    """sparse_path がオプション偽装・パストラバーサル・絶対パスでないことを検証する。"""
    if value.startswith("-"):
        raise ValueError(f"sparse_path は '-' で始まることはできません: '{value}'")
    if ".." in value.split("/"):
        raise ValueError(f"sparse_path に '..' を含めることはできません: '{value}'")
    if value.startswith("/"):
        raise ValueError(f"sparse_path は絶対パスにできません: '{value}'")


def _git(*args: str) -> list[str]:
    """安全フラグ付き git コマンドのargv を返す。"""
    return ["git"] + _GIT_SAFE_FLAGS + list(args)


_REQUIRED_SPEC_KEYS = (
    "schema_version", "git_remote", "git_commit", "sparse_paths",
    "merged_sha256", "parts", "auxiliary_files",
    "signed_tag", "signer_key_fingerprint",
)

# signed_tag: models/<7-40hex>-<quant>
_SIGNED_TAG_RE = re.compile(r"^models/[0-9a-f]{7,40}-(fp32|fp16|int8)$")
# signer_key_fingerprint: 40 桁大文字 hex（GPG long key fingerprint）
_FINGERPRINT_RE = re.compile(r"^[0-9A-F]{40}$")


def _load_sources_spec(sources_json: Path) -> dict:
    """model_sources.json を読み込み、必須フィールドとスキーマバージョンを検証して返す。"""
    if not sources_json.exists():
        raise FileNotFoundError(f"model_sources.json が見つかりません: {sources_json}")
    spec = json.loads(sources_json.read_text(encoding="utf-8"))
    for key in _REQUIRED_SPEC_KEYS:
        if key not in spec:
            raise ValueError(f"model_sources.json に必須キーがありません: '{key}'")
    if spec["schema_version"] != 1:
        raise ValueError(f"未対応の schema_version: {spec['schema_version']}")
    if not spec["parts"]:
        raise ValueError("model_sources.json の 'parts' が空です")
    if not spec["sparse_paths"]:
        raise ValueError("model_sources.json の 'sparse_paths' が空です")
    if not _SIGNED_TAG_RE.match(spec["signed_tag"]):
        raise ValueError(f"signed_tag の形式が不正: '{spec['signed_tag']}'")
    if not _FINGERPRINT_RE.match(spec["signer_key_fingerprint"]):
        raise ValueError(f"signer_key_fingerprint の形式が不正: '{spec['signer_key_fingerprint']}'")
    return spec


def _is_already_assembled(target_dir: Path, spec: dict) -> bool:
    """統合済み model.onnx が存在し、SHA256 が一致すれば True を返す。"""
    model_path = target_dir / "model.onnx"
    if not model_path.exists():
        return False
    expected = spec["merged_sha256"]
    try:
        _validate_sha256_format(expected, "merged_sha256")
    except ValueError:
        return False
    actual = _sha256_path(model_path)
    return hmac.compare_digest(actual, expected)


def _verify_signed_tag(spec: dict, clone_dir_str: str, git_env: dict) -> None:
    """git tag 署名と鍵指紋を検証する。

    DEVGEAR_SKIP_SIGNATURE_VERIFY=1 が設定されている場合のみスキップ（CI/開発用・本番禁止）。
    """
    if os.environ.get("DEVGEAR_SKIP_SIGNATURE_VERIFY") == "1":
        log.warning("DEVGEAR_SKIP_SIGNATURE_VERIFY=1: 署名検証をスキップします（本番禁止）")
        return

    signed_tag: str = spec["signed_tag"]
    expected_fp: str = spec["signer_key_fingerprint"]
    commit: str = spec["git_commit"]

    # tag を fetch する
    subprocess.run(
        _git("-C", clone_dir_str, "fetch", "--depth=1", "origin", "tag", signed_tag),
        check=True, capture_output=True, env=git_env,
    )

    # 署名検証（--raw で機械可読 GNUPG status を stderr に出力）
    result = subprocess.run(
        _git("-C", clone_dir_str, "verify-tag", "--raw", signed_tag),
        check=False, capture_output=True, env=git_env,
    )
    if result.returncode != 0:
        raise ValueError(f"tag 署名検証失敗: {signed_tag}")

    # "[GNUPG:] VALIDSIG <fingerprint> ..." 行から指紋を抽出する
    actual_fp = ""
    for line in result.stderr.decode("utf-8", errors="replace").splitlines():
        if line.startswith("[GNUPG:] VALIDSIG "):
            actual_fp = line.split()[2]
            break
    if not actual_fp:
        raise ValueError(f"tag 署名から鍵指紋を抽出できません: {signed_tag}")
    if not hmac.compare_digest(actual_fp.upper(), expected_fp.upper()):
        raise ValueError(f"鍵指紋不一致: expected={expected_fp} actual={actual_fp}")

    # tag が指す commit が spec.git_commit と一致するか確認する
    tag_commit = subprocess.run(
        _git("-C", clone_dir_str, "rev-list", "-n", "1", signed_tag),
        check=True, capture_output=True, env=git_env,
    ).stdout.decode("utf-8").strip()
    if not hmac.compare_digest(tag_commit, commit):
        raise ValueError(f"tag commit 不一致: tag={tag_commit} spec={commit}")


def _sparse_checkout(spec: dict, work_dir: Path) -> Path:
    """git sparse-checkout で assets/models だけを取得する。

    work_dir は tempfile.TemporaryDirectory 内の Path。
    取得した sparse tree のルートディレクトリを返す。
    DEVGEAR_MODEL_REMOTE は DEVGEAR_TESTING=1 の時のみ有効（テスト専用）。
    """
    testing_mode = os.environ.get("DEVGEAR_TESTING") == "1"
    env_remote = os.environ.get("DEVGEAR_MODEL_REMOTE")
    if env_remote and not testing_mode:
        log.warning("DEVGEAR_MODEL_REMOTE は DEVGEAR_TESTING=1 なしでは無視されます")
        env_remote = None
    remote: str = env_remote or spec["git_remote"]
    commit: str = spec["git_commit"]
    sparse_paths: list[str] = spec["sparse_paths"]

    _validate_remote(remote)
    _validate_git_commit(commit)
    for sp in sparse_paths:
        _validate_sparse_path(sp)

    clone_dir = work_dir / "repo"
    clone_dir.mkdir()
    clone_dir_str = str(clone_dir)

    log.info("git sparse-checkout: %s@%s", remote, commit[:8])

    git_env = _make_git_env()

    def _run(*args: str) -> None:
        """安全フラグ付き git を実行し、失敗時は stderr をログに出す。"""
        try:
            subprocess.run(
                _git(*args),
                check=True,
                capture_output=True,
                env=git_env,
            )
        except subprocess.CalledProcessError as exc:
            log.error("git 失敗: %s\nstderr: %s", list(args), exc.stderr.decode(errors="replace"))
            raise

    # クローン（blob なし、depth=1、チェックアウトなし）
    _run("clone", "--filter=blob:none", "--no-checkout", "--depth=1", "--sparse", remote, clone_dir_str)

    # git tag 署名を検証する（サプライチェーン信頼境界の確立）
    _verify_signed_tag(spec, clone_dir_str, git_env)

    # sparse-checkout を cone モードで設定
    _run("-C", clone_dir_str, "sparse-checkout", "init", "--cone")
    _run("-C", clone_dir_str, "sparse-checkout", "set", *sparse_paths)

    # 指定 commit をチェックアウト
    _run("-C", clone_dir_str, "checkout", commit)

    return clone_dir


def _verify_parts(assets_dir: Path, spec: dict) -> None:
    """各 part の SHA256 を検証する。parts 配列は model.onnx.part00 から始まる単調増加を要求する。"""
    parts = spec["parts"]
    # parts の名前が model.onnx.partNN の単調増加（0始まり）であることを確認
    for expected_idx, part in enumerate(parts):
        name: str = part["name"]
        prefix = "model.onnx.part"
        if not name.startswith(prefix):
            raise ValueError(f"parts[{expected_idx}] の名前が不正: {repr(name)}")
        try:
            actual_idx = int(name.removeprefix(prefix))
        except ValueError as exc:
            raise ValueError(f"parts[{expected_idx}] のインデックスが数値でない: {repr(name)}") from exc
        if actual_idx != expected_idx:
            raise ValueError(
                f"parts の順序が不正: インデックス {expected_idx} に {repr(name)} (idx={actual_idx}) があります"
            )

    for part in parts:
        name = part["name"]
        expected: str = part["sha256"]
        _validate_sha256_format(expected, name)
        # assets_dir 配下の sparse_paths[0] にファイルがある
        sparse_rel = spec["sparse_paths"][0]  # e.g. "assets/models"
        part_path = _safe_join(assets_dir / sparse_rel, name)
        if not part_path.exists():
            raise FileNotFoundError(f"part が見つかりません: {part_path}")
        actual = _sha256_path(part_path)
        if not hmac.compare_digest(actual, expected):
            raise ValueError(
                f"SHA256 不一致: {name}\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}"
            )
    log.info("part 検証完了: %d 個", len(parts))


def _merge_and_verify(assets_dir: Path, target_dir: Path, spec: dict) -> None:
    """part を統合して target_dir/model.onnx に書き出す（atomic rename）。"""
    import hashlib

    from devgear.mem._paths import _CHUNK

    sparse_rel = spec["sparse_paths"][0]
    model_src_dir = assets_dir / sparse_rel

    if target_dir.is_symlink():
        raise ValueError(f"target_dir はシンボリックリンクにできません: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    target_dir.chmod(0o700)

    tmp_path = target_dir / "model.onnx.tmp"
    h = hashlib.sha256()

    try:
        with tmp_path.open("wb") as out_f:
            for part in spec["parts"]:
                part_path = _safe_join(model_src_dir, part["name"])
                with part_path.open("rb") as in_f:
                    for chunk in iter(lambda: in_f.read(_CHUNK), b""):
                        out_f.write(chunk)
                        h.update(chunk)

        actual = h.hexdigest()
        expected = spec["merged_sha256"]
        _validate_sha256_format(expected, "merged_sha256")
        if not hmac.compare_digest(actual, expected):
            raise ValueError(
                f"統合後 SHA256 不一致\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}"
            )

        # atomic rename（同一ファイルシステム内）
        os.replace(tmp_path, target_dir / "model.onnx")
        log.info("model.onnx 統合完了: %s", target_dir / "model.onnx")

    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _copy_auxiliary(assets_dir: Path, target_dir: Path, spec: dict) -> None:
    """tokenizer.json / config.json / manifest.json を SHA256 検証付きでコピーする。

    各ファイルは git tag 署名検証済みの sparse tree 由来であり、
    model_sources.json の auxiliary_files SHA256 で内容を確認する。
    """
    sparse_rel = spec["sparse_paths"][0]
    model_src_dir = assets_dir / sparse_rel

    sha_map = {a["name"]: a["sha256"] for a in spec.get("auxiliary_files", [])}

    for fname in ["tokenizer.json", "config.json", "manifest.json"]:
        src = model_src_dir / fname
        if not src.exists():
            if fname == "manifest.json":
                # manifest.json は必須
                raise FileNotFoundError(f"manifest.json が見つかりません: {src}")
            log.warning("%s が見つかりません。スキップします。", fname)
            continue

        if fname in sha_map:
            expected = sha_map[fname]
            _validate_sha256_format(expected, fname)
            actual = _sha256_path(src)
            if not hmac.compare_digest(actual, expected):
                raise ValueError(
                    f"{fname} SHA256 不一致\n"
                    f"  expected: {expected}\n"
                    f"  actual:   {actual}"
                )

        dst = _safe_join(target_dir, fname)
        shutil.copy2(src, dst)
        log.info("%s コピー完了", fname)


def _mean_pool_l2(token_embs: Any, attention_mask: Any) -> Any:
    """mean pooling + L2 正規化を適用する（ruri-v3 仕様）。

    embedding.py の _encode と model_assembler の _sanity_inference で共用する。
    """
    import numpy as np  # type: ignore[import-untyped]

    mask = attention_mask.astype(np.float32)[:, :, np.newaxis]
    summed = (token_embs * mask).sum(axis=1)
    counts = mask.sum(axis=1).clip(min=1e-9)
    mean_vecs = summed / counts
    norms = np.linalg.norm(mean_vecs, axis=1, keepdims=True).clip(min=1e-9)
    return mean_vecs / norms


def _sanity_inference(target_dir: Path) -> None:
    """ONNX 推論を 1 回実行し、dim=768 かつ L2 norm≈1.0 であることを確認する。"""
    import numpy as np  # type: ignore[import-untyped]
    import onnxruntime as ort  # type: ignore[import-untyped]
    from tokenizers import Tokenizer  # type: ignore[import-untyped]

    model_path = target_dir / "model.onnx"
    tok_path = target_dir / "tokenizer.json"

    sess_opts = ort.SessionOptions()
    sess_opts.log_severity_level = 3
    session = ort.InferenceSession(
        str(model_path), sess_opts, providers=["CPUExecutionProvider"]
    )

    tokenizer = Tokenizer.from_file(str(tok_path))
    tokenizer.enable_padding(pad_token="[PAD]", length=512)
    tokenizer.enable_truncation(max_length=512)

    text = "検索クエリ: サニティチェック"
    enc = tokenizer.encode(text)
    input_ids = np.array([enc.ids], dtype=np.int64)
    attention_mask = np.array([enc.attention_mask], dtype=np.int64)

    inputs: dict = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
    }
    if any(inp.name == "token_type_ids" for inp in session.get_inputs()):
        inputs["token_type_ids"] = np.zeros_like(input_ids)

    outputs = session.run(None, inputs)
    token_embs = outputs[0]  # (1, seq_len, hidden_dim)

    vec = _mean_pool_l2(token_embs, attention_mask)[0]

    norm = math.sqrt(float(np.dot(vec, vec)))
    dim = len(vec)

    if dim != 768:
        raise ValueError(f"埋め込み次元が期待値と異なります: {dim} (expected 768)")
    if abs(norm - 1.0) > 1e-3:
        raise ValueError(f"L2 ノルムが期待値と異なります: {norm:.6f} (expected ≈1.0)")

    log.info("サニティ推論 OK: dim=%d, L2 norm=%.6f", dim, norm)


def assemble(sources_json: Path, target_dir: Path) -> None:
    """install エントリポイント。

    model_sources.json を読み、sparse-checkout で分割 part を取得し
    target_dir/model.onnx に統合する。統合済みで SHA が一致する場合はスキップ。
    """
    spec = _load_sources_spec(sources_json)

    if _is_already_assembled(target_dir, spec):
        log.info("スキップ: 既存の統合済みモデルを再利用します: %s", target_dir / "model.onnx")
        return

    with tempfile.TemporaryDirectory(prefix="devgear_assets_") as tmp:
        assets_dir = _sparse_checkout(spec, Path(tmp))
        _verify_parts(assets_dir, spec)
        _merge_and_verify(assets_dir, target_dir, spec)
        _copy_auxiliary(assets_dir, target_dir, spec)

    _sanity_inference(target_dir)
    log.info("モデル統合完了: %s", target_dir)


def main() -> None:  # pragma: no cover
    """CLI エントリポイント。"""
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    parser = argparse.ArgumentParser(
        prog="python3 -m devgear.mem.model_assembler",
        description="ONNX モデルを sparse-checkout で取得・統合する",
    )
    parser.add_argument(
        "--sources",
        type=Path,
        required=True,
        help="model_sources.json のパス",
    )
    parser.add_argument(
        "--target",
        type=Path,
        required=True,
        help="統合先ディレクトリ（~/.devgear/models 等）",
    )
    args = parser.parse_args()

    try:
        assemble(args.sources, args.target)
    except Exception as exc:
        log.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":  # pragma: no cover
    main()
