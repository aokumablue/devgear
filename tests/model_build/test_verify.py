"""verify モジュールのユニットテスト（ネットワーク不要）。"""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest
from model_build.verify import (
    _check_dim,
    _check_l2_norm,
    _check_reproducibility,
    _cosine_similarity,
)


class TestCosineSimilarity:
    """_cosine_similarity のテスト。"""

    def test_identical_vectors(self) -> None:
        """同一ベクトルのコサイン類似度は 1.0。"""
        v = [1.0, 0.0, 0.0]
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self) -> None:
        """直交ベクトルのコサイン類似度は 0.0。"""
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self) -> None:
        """逆向きベクトルのコサイン類似度は -1.0。"""
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_zero_vector_returns_zero(self) -> None:
        """零ベクトルが含まれる場合は 0.0 を返す。"""
        a = [0.0, 0.0]
        b = [1.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0


class TestCheckDim:
    """_check_dim のテスト。"""

    def test_correct_dim(self, capsys: pytest.CaptureFixture) -> None:
        """期待次元と一致すれば例外なし。"""
        vectors = [[0.1] * 768, [0.2] * 768]
        _check_dim(vectors, 768)
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_wrong_dim_raises(self) -> None:
        """期待次元と異なれば ValueError。"""
        vectors = [[0.1] * 512]
        with pytest.raises(ValueError, match="次元数不一致"):
            _check_dim(vectors, 768)


class TestCheckL2Norm:
    """_check_l2_norm のテスト。"""

    def test_unit_vectors_pass(self, capsys: pytest.CaptureFixture) -> None:
        """L2 norm ≈ 1.0 のベクトルは通過する。"""
        v = [1.0 / math.sqrt(768)] * 768
        _check_l2_norm([v])
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_non_unit_vector_raises(self) -> None:
        """L2 norm が 1.0 から外れたベクトルは ValueError。"""
        v = [1.0] * 768  # norm = sqrt(768) ≈ 27.7
        with pytest.raises(ValueError, match="L2 ノルム不正"):
            _check_l2_norm([v])


class TestCheckReproducibility:
    """_check_reproducibility のテスト。"""

    def _make_session_and_tokenizer(self, vec: list[float]) -> tuple[MagicMock, MagicMock]:
        """指定ベクトルを返す推論モックを作成する。"""
        import numpy as np

        mock_session = MagicMock()
        mock_session.get_inputs.return_value = []
        token_embs = np.array([[vec]], dtype=np.float32)
        mock_session.run.return_value = [token_embs]

        mock_tok = MagicMock()
        enc = MagicMock()
        enc.ids = [1, 2, 3]
        enc.attention_mask = [1, 1, 1]
        mock_tok.encode.return_value = enc

        return mock_session, mock_tok

    def test_identical_output_passes(self, capsys: pytest.CaptureFixture) -> None:
        """2 回同じ推論結果なら再現性チェック通過。"""
        vec = [1.0 / math.sqrt(3)] * 3
        ref_vec = list(vec)
        session, tokenizer = self._make_session_and_tokenizer(vec)

        _check_reproducibility(session, tokenizer, "test text", ref_vec, threshold=0.999)
        captured = capsys.readouterr()
        assert "OK" in captured.out

    def test_diverged_output_raises(self) -> None:
        """cosine 類似度が閾値未満なら ValueError。"""
        ref_vec = [1.0, 0.0, 0.0]
        diverged_vec = [0.0, 1.0, 0.0]
        session, tokenizer = self._make_session_and_tokenizer(diverged_vec)

        with pytest.raises(ValueError, match="再現性チェック失敗"):
            _check_reproducibility(session, tokenizer, "text", ref_vec, threshold=0.999)
