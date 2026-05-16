"""ONNX エクスポート — ruri-v3 を HF Hub から取得して FP32 ONNX 形式に変換する。

optimum.exporters.onnx.main_export を直接呼び出す（CLI には `--revision` がないため）。
量子化（FP16/INT8）は後段の quantize.py で行う。
メンテナ環境でのみ実行される。
"""

from __future__ import annotations

from pathlib import Path


def export_to_onnx(
    model_name: str,
    revision: str,
    output_dir: Path,
    opset: int = 17,
) -> Path:
    """指定モデルを FP32 ONNX 形式にエクスポートし、生成された ONNX ファイルのパスを返す。

    optimum.exporters.onnx.main_export を直接呼び出す。
    出力は output_dir/onnx_export/ に生成される。
    """
    from optimum.exporters.onnx import main_export  # type: ignore[import-untyped]

    onnx_out = output_dir / "onnx_export"
    onnx_out.mkdir(parents=True, exist_ok=True)

    print(
        f"[export] main_export(model={model_name}, revision={revision[:8]}, opset={opset})",
        flush=True,
    )
    main_export(
        model_name_or_path=model_name,
        output=onnx_out,
        task="feature-extraction",
        opset=opset,
        revision=revision,
        trust_remote_code=False,
        framework="pt",
        do_validation=False,
    )

    # 生成された ONNX ファイルを検索（model.onnx 優先）
    candidates = list(onnx_out.glob("model.onnx")) + list(onnx_out.glob("*.onnx"))
    if not candidates:
        raise FileNotFoundError(f"ONNX ファイルが {onnx_out} に見つかりません。")

    onnx_path = next((p for p in candidates if p.name == "model.onnx"), candidates[0])
    size_mb = onnx_path.stat().st_size / 1024**2
    print(f"[export] ONNX モデル: {onnx_path} ({size_mb:.1f} MB)", flush=True)
    return onnx_path
