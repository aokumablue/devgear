"""model_build CLI — `python3 -m model_build <subcommand>` で実行する。

サブコマンド:
  build    ONNX 変換 → 量子化 → 分割 → manifest 生成を一括実行
  verify   manifest.json を使って分割済みモデルを検証
  clean    output_dir の part ファイルと manifest を削除
  sources  manifest.json + git HEAD から model_sources.json を生成
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from model_build.quantize import DEFAULT_QUANT, QUANT_CHOICES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILD_CONFIG_PATH = Path(__file__).resolve().parent / "build_config.json"
_DEFAULT_OUT = _REPO_ROOT / "assets" / "models"
_DEFAULT_SOURCES_OUT = _REPO_ROOT / "plugins" / "devgear" / "model_sources.json"


def _load_build_config() -> dict:
    """build_config.json を読み込み、モデルメタデータを返す。"""
    if not _BUILD_CONFIG_PATH.exists():
        raise FileNotFoundError(f"build_config.json が見つかりません: {_BUILD_CONFIG_PATH}")
    config = json.loads(_BUILD_CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ("model_name", "hf_revision", "model_type", "num_heads", "hidden_size", "embedding_dim", "tokenizer_max_length"):
        if key not in config:
            raise ValueError(f"build_config.json に必須キーがありません: '{key}'")
    return config


def _default_git_remote() -> str:
    """現在のリポの git remote origin URL を取得する。失敗時はフォールバック値を返す。"""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "git@github.com:aokumablue/devgear.git"


def _cmd_build(args: argparse.Namespace) -> None:
    """ONNX 変換 → 量子化 → 分割 → manifest 生成を一括実行する。"""
    import tempfile

    from model_build.export import export_to_onnx
    from model_build.quantize import quantize
    from model_build.split import split

    build_cfg = _load_build_config()
    output_dir: Path = args.out
    quant: str = args.quant

    with tempfile.TemporaryDirectory(prefix="devgear_build_") as tmp:
        tmp_path = Path(tmp)

        # Step 1: ONNX エクスポート（常に FP32 で取得し、後段で量子化）
        print(
            f"[build] Step 1/3: ONNX エクスポート ({args.model}@{args.revision[:8]})",
            flush=True,
        )
        raw_onnx = export_to_onnx(
            model_name=args.model,
            revision=args.revision,
            output_dir=tmp_path,
        )

        # Step 2: 量子化（fp32: コピー、fp16: ort optimizer、int8: 動的量子化）
        print(f"[build] Step 2/3: 量子化 ({quant})", flush=True)
        quant_onnx = tmp_path / f"model_{quant}.onnx"
        quantize(raw_onnx, quant_onnx, quant, num_heads=build_cfg["num_heads"], hidden_size=build_cfg["hidden_size"])

        # tokenizer.json / config.json を取得（エクスポート出力から）
        onnx_export_dir = raw_onnx.parent
        tokenizer_json = onnx_export_dir / "tokenizer.json"
        config_json = onnx_export_dir / "config.json"
        if not tokenizer_json.exists():
            raise FileNotFoundError(f"tokenizer.json が見つかりません: {tokenizer_json}")
        if not config_json.exists():
            raise FileNotFoundError(f"config.json が見つかりません: {config_json}")

        # Step 3: 分割 + manifest 生成
        print(f"[build] Step 3/3: 分割 → {output_dir}", flush=True)
        split(
            model_onnx=quant_onnx,
            tokenizer_json=tokenizer_json,
            config_json=config_json,
            output_dir=output_dir,
            model_name=args.model,
            hf_revision=args.revision,
            quant=quant,
            embedding_dim=build_cfg["embedding_dim"],
            tokenizer_max_length=build_cfg["tokenizer_max_length"],
        )

    print("[build] 完了", flush=True)


def _cmd_verify(args: argparse.Namespace) -> None:
    """manifest.json を使って分割済みモデルを検証する。"""
    from model_build.verify import verify

    verify(args.model_dir, cosine_threshold=args.cosine_threshold)


def _cmd_clean(args: argparse.Namespace) -> None:
    """output_dir の part ファイルと manifest を削除する。

    symlink は対象外（assets/models は実ファイル前提）。
    """
    output_dir: Path = args.out
    if not output_dir.exists():
        print(f"[clean] ディレクトリが存在しません: {output_dir}", flush=True)
        return
    removed = 0
    for p in sorted(output_dir.glob("model.onnx.part*")):
        p.unlink()
        removed += 1
    manifest = output_dir / "manifest.json"
    if manifest.exists():
        manifest.unlink()
        removed += 1
    print(f"[clean] {removed} ファイルを削除しました: {output_dir}", flush=True)


def _get_git_head() -> str:
    """現在の git HEAD SHA を取得する（シェルインジェクション防止）。"""
    import subprocess
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _validate_fingerprint(value: str) -> str:
    """GPG 鍵指紋が 40 桁大文字 hex であることを検証して返す。"""
    import re
    if not re.match(r"^[0-9A-F]{40}$", value.upper()):
        raise argparse.ArgumentTypeError(f"signer-fingerprint は 40 桁大文字 hex が必要: '{value}'")
    return value.upper()


def _cmd_sources(args: argparse.Namespace) -> None:
    """manifest.json + git HEAD から model_sources.json を生成する。

    生成された JSON は install 時の git sparse-checkout 仕様として使用される。
    git_commit は現在の HEAD をピン留めし、サプライチェーン攻撃に耐性を持つ。
    signed_tag / signer_key_fingerprint で git tag 署名による信頼境界を確立する。
    """
    model_dir: Path = args.model_dir
    out_path: Path = args.out
    git_remote: str = args.git_remote
    signed_tag: str = args.signed_tag
    signer_fingerprint: str = args.signer_fingerprint

    manifest_path = model_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json が見つかりません: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    git_commit = _get_git_head()

    # assets/models への sparse path（リポルートからの相対パス）
    sparse_path = "assets/models"

    import hashlib

    # manifest.json 自身の SHA256 を計算して auxiliary_files に追加する（多層防御）
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    auxiliary_files = [
        {"name": "manifest.json", "sha256": manifest_sha256},
        *manifest["auxiliary_files"],
    ]

    sources = {
        "schema_version": 1,
        "model_name": manifest["model_name"],
        "git_remote": git_remote,
        "git_commit": git_commit,
        "signed_tag": signed_tag,
        "signer_key_fingerprint": signer_fingerprint,
        "sparse_paths": [sparse_path],
        "manifest_relpath": f"{sparse_path}/manifest.json",
        "merged_sha256": manifest["merged_sha256"],
        "parts": [
            {"name": p["name"], "sha256": p["sha256"]}
            for p in manifest["parts"]
        ],
        "auxiliary_files": auxiliary_files,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[sources] 生成: {out_path}", flush=True)
    print(f"[sources] git_commit: {git_commit}", flush=True)
    print(f"[sources] signed_tag: {signed_tag}", flush=True)


def main() -> None:
    """CLI エントリポイント。"""
    parser = argparse.ArgumentParser(
        prog="python3 -m model_build",
        description="devgear メンテナ向け ONNX ビルドツール",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- build ---
    _build_cfg = _load_build_config()
    p_build = sub.add_parser("build", help="ONNX 変換・量子化・分割を一括実行")
    p_build.add_argument("--model", default=_build_cfg["model_name"], help="HF Hub モデル ID")
    p_build.add_argument("--revision", default=_build_cfg["hf_revision"], help="HF Hub commit SHA")
    p_build.add_argument(
        "--quant",
        default=DEFAULT_QUANT,
        choices=QUANT_CHOICES,
        help=f"量子化レベル (default: {DEFAULT_QUANT})",
    )
    p_build.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="出力ディレクトリ")

    # --- verify ---
    p_verify = sub.add_parser("verify", help="分割済みモデルの検証")
    p_verify.add_argument(
        "--model-dir",
        type=Path,
        default=_DEFAULT_OUT,
        help="manifest.json が存在するディレクトリ",
    )
    p_verify.add_argument(
        "--cosine-threshold",
        type=float,
        default=0.999,
        help="再現性チェックの最低 cosine 類似度 (default: 0.999)",
    )

    # --- clean ---
    p_clean = sub.add_parser("clean", help="生成済み part・manifest を削除")
    p_clean.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="対象ディレクトリ")

    # --- sources ---
    p_sources = sub.add_parser("sources", help="manifest.json から model_sources.json を生成")
    p_sources.add_argument(
        "--model-dir",
        type=Path,
        default=_DEFAULT_OUT,
        help="manifest.json が存在するディレクトリ",
    )
    p_sources.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_SOURCES_OUT,
        help="生成先 model_sources.json のパス",
    )
    p_sources.add_argument(
        "--git-remote",
        default=_default_git_remote(),
        help="git remote URL (default: git remote get-url origin)",
    )
    p_sources.add_argument(
        "--signed-tag",
        required=True,
        dest="signed_tag",
        help="署名済み git tag 名 (例: models/a2f9ac6-fp16)",
    )
    p_sources.add_argument(
        "--signer-fingerprint",
        required=True,
        dest="signer_fingerprint",
        type=_validate_fingerprint,
        help="署名者 GPG 鍵指紋 (40 桁大文字 hex)",
    )

    args = parser.parse_args()

    try:
        if args.command == "build":
            _cmd_build(args)
        elif args.command == "verify":
            _cmd_verify(args)
        elif args.command == "clean":
            _cmd_clean(args)
        elif args.command == "sources":
            _cmd_sources(args)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
