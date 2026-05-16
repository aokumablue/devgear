"""モデル統合 — git sparse-checkout で分割 part を取得し ~/.devgear/models/ に統合する。

純標準ライブラリのみで動作する（hashlib, hmac, json, os, pathlib, shutil, subprocess, tempfile）。
onnxruntime / tokenizers は _sanity_inference のみで使用（install.sh 実行後に利用可能）。

CLI: python3 -m devgear.mem.model_assembler --sources <json> --target <dir>
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("MODEL_ASSEMBLER")

_SHA256_CHARS = frozenset("0123456789abcdef")
_CHUNK = 4 * 1024 * 1024  # 4 MB 読み取りバッファ


def _validate_sha256_format(value: str, label: str) -> None:
    """SHA256 文字列が 64 文字の16進数であることを検証する。"""
    if len(value) != 64 or not all(c in _SHA256_CHARS for c in value):
        raise ValueError(f"不正な SHA256 値 ({label}): '{value[:16]}...'")


def _safe_join(base: Path, name: str) -> Path:
    """name を base に結合し、base 配下に収まることを検証する（パストラバーサル防止）。"""
    resolved = (base / name).resolve()
    base_resolved = base.resolve()
    if not str(resolved).startswith(str(base_resolved) + "/") and resolved != base_resolved:
        raise ValueError(f"不正なパス: '{name}' は許可されたディレクトリ外を指しています")
    return resolved


def _sha256_path(path: Path) -> str:
    """ファイルの SHA256 ハッシュを返す（大ファイル対応）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_sources_spec(sources_json: Path) -> dict:
    """model_sources.json を読み込んで返す。"""
    if not sources_json.exists():
        raise FileNotFoundError(f"model_sources.json が見つかりません: {sources_json}")
    return json.loads(sources_json.read_text(encoding="utf-8"))


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


def _sparse_checkout(spec: dict, work_dir: str) -> Path:
    """git sparse-checkout で assets/models/ruri-v3-310m だけを取得する。

    work_dir は tempfile.TemporaryDirectory 内のパス。
    取得した sparse tree のルートディレクトリを返す。
    """
    remote: str = os.environ.get("DEVGEAR_MODEL_REMOTE") or spec["git_remote"]
    commit: str = spec["git_commit"]
    sparse_paths: list[str] = spec["sparse_paths"]

    clone_dir = os.path.join(work_dir, "repo")
    os.makedirs(clone_dir)

    log.info("git sparse-checkout: %s@%s", remote, commit[:8])

    # クローン（blob なし、depth=1、チェックアウトなし）
    subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", "--depth=1",
         "--sparse", remote, clone_dir],
        check=True,
        capture_output=True,
    )

    # sparse-checkout を cone モードで設定
    subprocess.run(
        ["git", "-C", clone_dir, "sparse-checkout", "init", "--cone"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", clone_dir, "sparse-checkout", "set"] + sparse_paths,
        check=True,
        capture_output=True,
    )

    # 指定 commit をチェックアウト
    subprocess.run(
        ["git", "-C", clone_dir, "checkout", commit],
        check=True,
        capture_output=True,
    )

    return Path(clone_dir)


def _verify_parts(assets_dir: Path, spec: dict) -> None:
    """各 part の SHA256 を検証する。"""
    for part in spec["parts"]:
        name: str = part["name"]
        expected: str = part["sha256"]
        _validate_sha256_format(expected, name)
        # assets_dir 配下の sparse_paths[0] にファイルがある
        sparse_rel = spec["sparse_paths"][0]  # e.g. "assets/models/ruri-v3-310m"
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
    log.info("part 検証完了: %d 個", len(spec["parts"]))


def _merge_and_verify(assets_dir: Path, target_dir: Path, spec: dict) -> None:
    """part を統合して target_dir/model.onnx に書き出す（atomic rename）。"""
    sparse_rel = spec["sparse_paths"][0]
    model_src_dir = assets_dir / sparse_rel

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
    """tokenizer.json / config.json / manifest.json を SHA256 検証付きでコピーする。"""
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


def _sanity_inference(target_dir: Path) -> None:
    """ONNX 推論を 1 回実行し、dim=768 かつ L2 norm≈1.0 であることを確認する。"""
    import math

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

    mask = attention_mask.astype(np.float32)[:, :, np.newaxis]
    summed = (token_embs * mask).sum(axis=1)
    counts = mask.sum(axis=1).clip(min=1e-9)
    vec = (summed / counts)[0]

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
        assets_dir = _sparse_checkout(spec, tmp)
        _verify_parts(assets_dir, spec)
        _merge_and_verify(assets_dir, target_dir, spec)
        _copy_auxiliary(assets_dir, target_dir, spec)

    _sanity_inference(target_dir)
    log.info("モデル統合完了: %s", target_dir)


def main() -> None:
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
        help="統合先ディレクトリ（~/.devgear/models/ruri-v3-310m 等）",
    )
    args = parser.parse_args()

    try:
        assemble(args.sources, args.target)
    except Exception as exc:
        log.error("%s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
