"""sentence-transformers ラッパー — 埋め込み生成"""

from __future__ import annotations

import sys
import threading

import torch

from devgear.mem.logger import get as _get_logger
from devgear.mem.settings import _DEFAULT_EMBEDDING_MODEL

log = _get_logger("EMBEDDING")

# torch 2.2.x は Python 3.12+ で torch.compile (Dynamo) を無効化している。
# ModernBERT は @torch.compile(dynamic=True) を使うため、起動時に no-op へ差し替える。
# torch 2.3+ では修正済みなので影響なし。
def _patch_torch_compile_if_needed() -> None:
    """torch.compile が Dynamo エラーを投げる環境では no-op に置換する"""
    try:
        torch.compile(lambda: None)
    except RuntimeError:
        def _noop_compile(fn=None, *args, **kwargs):  # type: ignore[no-untyped-def]
            return (lambda f: f) if fn is None else fn
        torch.compile = _noop_compile  # type: ignore[method-assign]
        log.debug("torch.compile を no-op に置換 (torch %s / Python %d.%d)", torch.__version__, *sys.version_info[:2])


_patch_torch_compile_if_needed()

# モデルはセッション終了時のみ使用するため、遅延ロード
_model = None
_model_name: str | None = None
_model_lock = threading.Lock()


def _get_model(model_name: str):  # type: ignore[no-untyped-def]
    global _model, _model_name
    with _model_lock:
        if _model is None or _model_name != model_name:
            log.info("モデルロード: %s", model_name)
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            _model = SentenceTransformer(model_name)
            _model_name = model_name
        return _model


def prefetch_model(model_name: str = _DEFAULT_EMBEDDING_MODEL) -> None:
    """埋め込みモデルをローカルキャッシュに事前取得する"""
    _get_model(model_name)


def embed(texts: list[str], model_name: str = _DEFAULT_EMBEDDING_MODEL) -> list[list[float]]:
    """テキストリストを埋め込みに変換する"""
    if not texts:
        return []
    model = _get_model(model_name)
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def embed_query(query: str, model_name: str = _DEFAULT_EMBEDDING_MODEL) -> list[float]:
    """検索クエリを埋め込みに変換する"""
    model = _get_model(model_name)
    # Ruri v3 の推奨プレフィックス
    embedding = model.encode(f"検索クエリ: {query}", show_progress_bar=False)
    return embedding.tolist()
