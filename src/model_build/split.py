"""分割 — ONNX ファイルを 45MB チャンクに分割し manifest.json を生成する。"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from model_build import __version__

CHUNK_SIZE = 45 * 1024 * 1024  # 45 MB（GitHub 推奨 50MB を下回るマージン）


def sha256_file(path: Path) -> str:
    """ファイルの SHA256 ハッシュを返す。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def split(
    model_onnx: Path,
    tokenizer_json: Path,
    config_json: Path,
    output_dir: Path,
    model_name: str,
    hf_revision: str,
    quant: str,
    embedding_dim: int = 768,
    tokenizer_max_length: int = 512,
) -> Path:
    """ONNX ファイルを分割して output_dir に書き出し、manifest.json パスを返す。

    既存の part ファイルは削除してから再生成する。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # 既存 part ファイルを削除
    for old in sorted(output_dir.glob("model.onnx.part*")):
        old.unlink()

    # モデルを分割して書き出す
    parts: list[dict] = []
    idx = 0
    with model_onnx.open("rb") as f:
        while True:
            data = f.read(CHUNK_SIZE)
            if not data:
                break
            part_name = f"model.onnx.part{idx:02d}"
            part_path = output_dir / part_name
            part_path.write_bytes(data)
            parts.append({
                "name": part_name,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            })
            idx += 1

    print(f"[split] {len(parts)} 個に分割: {output_dir}", flush=True)

    # 補助ファイルをコピーして SHA256 を計算
    aux_dst_tok = output_dir / "tokenizer.json"
    aux_dst_cfg = output_dir / "config.json"
    shutil.copy2(tokenizer_json, aux_dst_tok)
    shutil.copy2(config_json, aux_dst_cfg)

    auxiliary: list[dict] = [
        {"name": "tokenizer.json", "sha256": sha256_file(aux_dst_tok)},
        {"name": "config.json", "sha256": sha256_file(aux_dst_cfg)},
    ]

    merged_sha256 = sha256_file(model_onnx)

    manifest = {
        "model_name": model_name,
        "hf_revision": hf_revision,
        "quantization": quant,
        "embedding_dim": embedding_dim,
        "tokenizer_max_length": tokenizer_max_length,
        "merged_sha256": merged_sha256,
        "parts": parts,
        "auxiliary_files": auxiliary,
        "created_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "tool_version": f"model_build/{__version__}",
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[split] manifest: {manifest_path}", flush=True)
    return manifest_path
