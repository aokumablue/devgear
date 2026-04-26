"""embedding モジュールのテスト"""

from __future__ import annotations

import sys
import types

import pytest
from devgear.mem import embedding


class FakeArray:
    def __init__(self, value):
        self._value = value

    def tolist(self):
        return self._value


class FakeSentenceTransformer:
    calls: list[str] = []

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.__class__.calls.append(model_name)

    def encode(self, value, show_progress_bar: bool = False):
        if isinstance(value, list):
            return FakeArray([[float(len(item))] for item in value])
        return FakeArray([float(len(value))])


@pytest.fixture(autouse=True)
def reset_embedding_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(embedding, "_model", None)
    monkeypatch.setattr(embedding, "_model_name", None)
    FakeSentenceTransformer.calls.clear()


def test_embed_returns_empty_list_without_loading_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    assert embedding.embed([]) == []
    assert FakeSentenceTransformer.calls == []


def test_embed_and_query_use_lazy_cached_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    assert embedding.embed(["one", "two"], model_name="model-a") == [[3.0], [3.0]]
    assert embedding.embed_query("search", model_name="model-a") == [13.0]
    assert embedding.embed(["z"], model_name="model-b") == [[1.0]]
    assert FakeSentenceTransformer.calls == ["model-a", "model-b"]


def test_prefetch_model_initializes_the_default_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    embedding.prefetch_model()
    assert FakeSentenceTransformer.calls == ["cl-nagoya/ruri-v3-310m"]


def test_prefetch_model_is_idempotent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )

    embedding.prefetch_model("model-a")
    embedding.prefetch_model("model-a")
    assert FakeSentenceTransformer.calls == ["model-a"]
