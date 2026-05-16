"""ONNX Runtime ラッパー — 埋め込み生成。

sentence-transformers / torch / transformers に依存しない。
モデルは ~/.devgear/models/model.onnx を使用する。
install.sh が model_assembler.py を呼び出して統合済みファイルを生成する。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from pathlib import Path
from typing import Any

from devgear.mem.logger import get as _get_logger
from devgear.mem.model_assembler import _mean_pool_l2
from devgear.mem.settings import _DEFAULT_EMBEDDING_MODEL, _DEFAULT_EMBEDDING_REVISION

log = _get_logger("EMBEDDING")

_SHA256_CHARS = frozenset("0123456789abcdef")

# 統合済み model.onnx は ~/.devgear/models/ に格納（install.sh が配置）
_MODELS_DIR = Path.home() / ".devgear" / "models"

# セッションはプロセス内でシングルトン（スレッドセーフ）
_session: Any = None
_tokenizer: Any = None
_lock = threading.Lock()

# ruri-v3 の最大トークン長
_MAX_LENGTH = 512


def _validate_sha256_format(value: str, label: str) -> None:
    """SHA256 文字列が 64 文字の16進数であることを検証する。"""
    if len(value) != 64 or not all(c in _SHA256_CHARS for c in value):
        raise ValueError(f"不正な SHA256 値 ({label}): '{value[:16]}...'")


def _verify_model_sha(models_dir: Path) -> None:
    """manifest.json の merged_sha256 と model.onnx の SHA256 を照合する。

    install 時に検証済みだが、起動時に 1 度だけ簡易チェックする。
    """
    manifest_path = models_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"manifest.json が見つかりません: {manifest_path}\n"
            "plugins/devgear/install.sh を実行してモデルを再統合してください。"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["merged_sha256"]
    _validate_sha256_format(expected, "merged_sha256")
    model_path = models_dir / "model.onnx"
    actual = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise ValueError(
            f"model.onnx SHA256 不一致\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}\n"
            "install.sh を再実行してモデルを再統合してください。"
        )


def _verify_tokenizer(tok_path: Path, models_dir: Path) -> None:
    """manifest.json の auxiliary_files を参照して tokenizer.json の SHA256 を検証する。"""
    manifest_path = models_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for aux in manifest.get("auxiliary_files", []):
        if aux["name"] != "tokenizer.json":
            continue
        expected = aux["sha256"]
        _validate_sha256_format(expected, "tokenizer.json")
        actual = hashlib.sha256(tok_path.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise ValueError(
                f"tokenizer.json SHA256 不一致\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}"
            )
        return
    raise ValueError("manifest.json に tokenizer.json のエントリがありません")


def _get_session() -> tuple[Any, Any]:
    """ONNX セッションとトークナイザをスレッドセーフにシングルトンでロードする。

    統合済み model.onnx を InferenceSession に直接渡す。
    """
    global _session, _tokenizer
    with _lock:
        if _session is None or _tokenizer is None:
            model_path = _MODELS_DIR / "model.onnx"
            tok_path = _MODELS_DIR / "tokenizer.json"

            if not model_path.exists():
                raise FileNotFoundError(
                    f"model.onnx が見つかりません: {model_path}\n"
                    "plugins/devgear/install.sh を実行してモデルを統合してください。"
                )
            if not tok_path.exists():
                raise FileNotFoundError(
                    f"tokenizer.json が見つかりません: {tok_path}\n"
                    "plugins/devgear/install.sh を実行してモデルを統合してください。"
                )

            import onnxruntime as ort  # type: ignore[import-untyped]
            from tokenizers import Tokenizer  # type: ignore[import-untyped]

            log.info(
                "モデルロード: %s@%s",
                _DEFAULT_EMBEDDING_MODEL,
                _DEFAULT_EMBEDDING_REVISION[:8],
            )

            # 起動時に model.onnx の SHA を簡易確認（install 時の検証の再確認）
            _verify_model_sha(_MODELS_DIR)

            # L-1: 実行時に tokenizer.json を manifest の SHA256 で検証
            _verify_tokenizer(tok_path, _MODELS_DIR)

            sess_opts = ort.SessionOptions()
            sess_opts.log_severity_level = 3  # ERROR のみ
            sess_opts.enable_mem_pattern = False
            sess_opts.intra_op_num_threads = 1
            _session = ort.InferenceSession(
                str(model_path),
                sess_opts,
                providers=["CPUExecutionProvider"],
            )
            _tokenizer = Tokenizer.from_file(str(tok_path))
            _tokenizer.enable_padding(pad_token="[PAD]", length=_MAX_LENGTH)
            _tokenizer.enable_truncation(max_length=_MAX_LENGTH)

        return _session, _tokenizer


def _encode(texts: list[str]) -> list[list[float]]:
    """テキストリストを ONNX 推論でベクトル化する。

    mean pooling + L2 正規化を適用する（ruri-v3 仕様）。
    """
    import numpy as np  # type: ignore[import-untyped]

    session, tokenizer = _get_session()
    encodings = tokenizer.encode_batch(texts)

    input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
    attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

    inputs: dict = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
    }
    # token_type_ids が必要なモデルにのみ渡す
    if any(inp.name == "token_type_ids" for inp in session.get_inputs()):
        inputs["token_type_ids"] = np.zeros_like(input_ids)

    outputs = session.run(None, inputs)
    token_embs = outputs[0]  # (batch, seq_len, hidden_dim)

    return _mean_pool_l2(token_embs, attention_mask).tolist()


def embed(texts: list[str]) -> list[list[float]]:
    """テキストリストを埋め込みに変換する。"""
    if not texts:
        return []
    return _encode(texts)


def embed_query(query: str) -> list[float]:
    """検索クエリを埋め込みに変換する。ruri-v3 推奨プレフィックスを付与する。"""
    result = _encode([f"検索クエリ: {query}"])
    return result[0]
