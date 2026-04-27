"""generate_review モジュールのテスト。"""

from __future__ import annotations

import io
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from devgear.skills.eval_viewer import generate_review as gr


def _make_workspace(tmp_path: Path) -> tuple[Path, Path]:
    workspace = tmp_path / "workspace"
    run_dir = workspace / "project" / "run-1"
    outputs = run_dir / "outputs"
    outputs.mkdir(parents=True)
    (run_dir / "eval_metadata.json").write_text(json.dumps({"prompt": "Find bugs", "eval_id": 1}), encoding="utf-8")
    (run_dir / "grading.json").write_text(json.dumps({"score": 1}), encoding="utf-8")
    (outputs / "artifact.txt").write_text("artifact", encoding="utf-8")
    (outputs / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (outputs / "report.pdf").write_bytes(b"%PDF-1.4")
    (outputs / "sheet.xlsx").write_bytes(b"PK\x03\x04")
    (outputs / "blob.bin").write_bytes(b"binary")
    (outputs / "transcript.md").write_text("ignored", encoding="utf-8")
    return workspace, run_dir


def _make_handler(
    *,
    path: str,
    workspace: Path,
    feedback_path: Path,
    previous: dict[str, dict] | None = None,
    benchmark_path: Path | None = None,
    body: bytes = b"",
) -> tuple[SimpleNamespace, list[int], list[tuple[str, str]], list[int], io.BytesIO]:
    responses: list[int] = []
    headers: list[tuple[str, str]] = []
    errors: list[int] = []
    wfile = io.BytesIO()
    handler = SimpleNamespace(
        path=path,
        workspace=workspace,
        skill_name="skill-name",
        feedback_path=feedback_path,
        previous=previous or {},
        benchmark_path=benchmark_path,
        wfile=wfile,
        rfile=io.BytesIO(body),
        headers={"Content-Length": str(len(body))},
        send_response=lambda code: responses.append(code),
        send_header=lambda key, value: headers.append((key, value)),
        end_headers=lambda: None,
        send_error=lambda code: errors.append(code),
    )
    return handler, responses, headers, errors, wfile


def test_embed_file_covers_main_types_and_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text_file = tmp_path / "doc.md"
    text_file.write_text("hello", encoding="utf-8")
    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    pdf_file = tmp_path / "report.pdf"
    pdf_file.write_bytes(b"%PDF")
    xlsx_file = tmp_path / "sheet.xlsx"
    xlsx_file.write_bytes(b"PK\x03\x04")
    binary_file = tmp_path / "blob.bin"
    binary_file.write_bytes(b"binary")
    broken_text = tmp_path / "broken.md"
    broken_text.write_text("broken", encoding="utf-8")
    broken_binary = tmp_path / "broken.bin"
    broken_binary.write_bytes(b"broken")

    original_read_text = Path.read_text
    original_read_bytes = Path.read_bytes

    def fake_read_text(self: Path, *args, **kwargs):  # noqa: ANN001
        if self == broken_text:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    def fake_read_bytes(self: Path, *args, **kwargs):  # noqa: ANN001
        if self == broken_binary:
            raise OSError("boom")
        return original_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    assert gr.embed_file(text_file)["type"] == "text"
    assert gr.embed_file(image_file)["type"] == "image"
    assert gr.embed_file(pdf_file)["type"] == "pdf"
    assert gr.embed_file(xlsx_file)["type"] == "xlsx"
    assert gr.embed_file(binary_file)["type"] == "binary"
    assert gr.embed_file(broken_text)["content"] == "(ファイルの読み込みに失敗しました)"
    assert gr.embed_file(broken_binary)["type"] == "error"


def test_build_run_prefers_metadata_and_filters_metadata_files(tmp_path: Path) -> None:
    workspace, run_dir = _make_workspace(tmp_path)

    run = gr.build_run(workspace, run_dir)

    assert run is not None
    assert run["prompt"] == "Find bugs"
    assert run["eval_id"] == 1
    assert sorted(file_info["name"] for file_info in run["outputs"]) == [
        "artifact.txt",
        "blob.bin",
        "image.png",
        "report.pdf",
        "sheet.xlsx",
    ]
    assert run["grading"] == {"score": 1}


def test_build_run_falls_back_to_transcript_and_parent_grading(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    run_dir = root / "group" / "run-2"
    outputs = run_dir / "outputs"
    outputs.mkdir(parents=True)
    (run_dir / "transcript.md").write_text("## Eval Prompt\n\nPrompt from transcript\n", encoding="utf-8")
    (run_dir.parent / "grading.json").write_text(json.dumps({"score": 2}), encoding="utf-8")
    (outputs / "artifact.txt").write_text("artifact", encoding="utf-8")

    run = gr.build_run(root, run_dir)

    assert run is not None
    assert run["prompt"] == "Prompt from transcript"
    assert run["eval_id"] is None
    assert run["grading"] == {"score": 2}


def test_load_previous_iteration_merges_feedback_and_outputs(tmp_path: Path) -> None:
    workspace, run_dir = _make_workspace(tmp_path)
    feedback_path = workspace / "feedback.json"
    feedback_path.write_text(
        json.dumps({"reviews": [{"run_id": "project-run-1", "feedback": "great"}, {"run_id": "missing", "feedback": "orphan"}]}),
        encoding="utf-8",
    )

    previous = gr.load_previous_iteration(workspace)

    assert previous["project-run-1"]["feedback"] == "great"
    assert previous["project-run-1"]["outputs"]
    assert previous["missing"]["feedback"] == "orphan"
    assert previous["missing"]["outputs"] == []


def test_generate_html_embeds_previous_and_benchmark(tmp_path: Path) -> None:
    template = Path(gr.__file__).with_name("viewer.html")
    runs = [{"id": "run-1", "prompt": "Prompt", "outputs": []}]
    html = gr.generate_html(
        runs,
        "skill-name",
        previous={"run-1": {"feedback": "ok", "outputs": [{"name": "artifact.txt"}]}},
        benchmark={"score": 1},
    )

    assert "const EMBEDDED_DATA" in html
    assert "skill-name" in html
    assert "ok" in html
    assert "artifact.txt" in html
    assert template.read_text(encoding="utf-8").split("/*__EMBEDDED_DATA__*/")[0] in html


def test_kill_port_logs_when_lsof_missing(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(gr.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")))

    gr._kill_port(3117)

    assert "lsof が見つからない" in capsys.readouterr().err


def test_kill_port_terminates_pids(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[int] = []

    monkeypatch.setattr(gr.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="123\n456\n"))
    monkeypatch.setattr(gr.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(gr.time, "sleep", lambda seconds: None)

    gr._kill_port(3117)

    assert killed == [123, 456]


def test_review_handler_get_routes(tmp_path: Path) -> None:
    workspace, run_dir = _make_workspace(tmp_path)
    feedback_path = workspace / "feedback.json"
    benchmark_path = workspace / "benchmark.json"
    benchmark_path.write_text(json.dumps({"score": 1}), encoding="utf-8")
    feedback_path.write_text(json.dumps({"reviews": [{"run_id": "project-run-1", "feedback": "nice"}]}), encoding="utf-8")

    handler, responses, headers, errors, wfile = _make_handler(
        path="/",
        workspace=workspace,
        feedback_path=feedback_path,
        previous={},
        benchmark_path=benchmark_path,
    )

    gr.ReviewHandler.do_GET(handler)

    assert responses == [200]
    assert ("Content-Type", "text/html; charset=utf-8") in headers
    assert errors == []
    assert b"EMBEDDED_DATA" in wfile.getvalue()

    handler, responses, headers, errors, wfile = _make_handler(
        path="/api/feedback",
        workspace=workspace,
        feedback_path=feedback_path,
        previous={},
    )
    gr.ReviewHandler.do_GET(handler)
    assert responses == [200]
    assert ("Content-Type", "application/json") in headers
    assert wfile.getvalue() == feedback_path.read_bytes()

    handler, responses, headers, errors, wfile = _make_handler(
        path="/missing",
        workspace=workspace,
        feedback_path=feedback_path,
    )
    gr.ReviewHandler.do_GET(handler)
    assert errors == [404]


def test_review_handler_post_routes(tmp_path: Path) -> None:
    workspace, _ = _make_workspace(tmp_path)
    feedback_path = workspace / "feedback.json"

    body = json.dumps({"reviews": [{"run_id": "project-run-1", "feedback": "great"}]}).encode("utf-8")
    handler, responses, headers, errors, wfile = _make_handler(
        path="/api/feedback",
        workspace=workspace,
        feedback_path=feedback_path,
        body=body,
    )

    gr.ReviewHandler.do_POST(handler)

    assert responses == [200]
    assert feedback_path.exists()
    assert json.loads(feedback_path.read_text(encoding="utf-8"))["reviews"][0]["feedback"] == "great"
    assert json.loads(wfile.getvalue()) == {"ok": True}

    bad_handler, responses, headers, errors, wfile = _make_handler(
        path="/api/feedback",
        workspace=workspace,
        feedback_path=feedback_path,
        body=json.dumps({"wrong": []}).encode("utf-8"),
    )
    gr.ReviewHandler.do_POST(bad_handler)
    assert responses == [500]
    assert json.loads(wfile.getvalue())["error"]


def test_main_static_and_server_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    workspace, run_dir = _make_workspace(tmp_path)
    static_path = tmp_path / "out.html"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_review.py",
            str(workspace),
            "--static",
            str(static_path),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        gr.main()
    assert excinfo.value.code == 0
    assert static_path.exists()
    assert "静的ビューアを書き出しました" in capsys.readouterr().out

    fake_state = {"calls": 0}

    class FakeServer:
        def __init__(self, address, handler):  # noqa: ANN001
            fake_state["calls"] += 1
            if fake_state["calls"] == 1:
                raise OSError("busy")
            self.server_address = (address[0], 4321)

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            fake_state["closed"] = True

    monkeypatch.setattr(gr, "_kill_port", lambda port: None)
    monkeypatch.setattr(gr, "HTTPServer", FakeServer)
    monkeypatch.setattr(gr.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_review.py",
            str(workspace),
        ],
    )

    gr.main()
    output = capsys.readouterr().out
    assert "レビュー表示" in output
    assert "終了しました。" in output


def test_main_rejects_invalid_workspace_and_empty_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setattr(sys, "argv", ["generate_review.py", str(missing)])
    with pytest.raises(SystemExit) as excinfo:
        gr.main()
    assert excinfo.value.code == 1
    assert "ディレクトリではありません" in capsys.readouterr().err

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(sys, "argv", ["generate_review.py", str(workspace)])
    with pytest.raises(SystemExit) as excinfo:
        gr.main()
    assert excinfo.value.code == 1
    assert "run が見つかりません" in capsys.readouterr().err


def test_find_runs_handles_non_dir_and_none_build_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = tmp_path / "not-a-directory.txt"
    file_path.write_text("content", encoding="utf-8")
    assert gr.find_runs(file_path) == []

    workspace, _ = _make_workspace(tmp_path / "workspace")
    monkeypatch.setattr(gr, "build_run", lambda root, current: None)
    assert gr.find_runs(workspace) == []


def test_build_run_handles_invalid_metadata_transcript_and_grading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, run_dir = _make_workspace(tmp_path)
    transcript = run_dir / "transcript.md"
    (run_dir / "eval_metadata.json").write_text("{bad", encoding="utf-8")
    (run_dir / "grading.json").write_text("{bad", encoding="utf-8")

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):  # noqa: ANN001
        if self == transcript:
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    run = gr.build_run(workspace, run_dir)
    assert run is not None
    assert run["prompt"] == "(プロンプトが見つかりません)"
    assert run["grading"] is None


def test_build_run_handles_transcript_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "workspace"
    run_dir = workspace / "project" / "run-1"
    outputs = run_dir / "outputs"
    outputs.mkdir(parents=True)
    (run_dir / "grading.json").write_text(json.dumps({"score": 1}), encoding="utf-8")
    (run_dir / "transcript.md").write_text("## Eval Prompt\n\nPrompt\n", encoding="utf-8")
    (run_dir / "eval_metadata.json").unlink(missing_ok=True)

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args, **kwargs):  # noqa: ANN001
        if self == run_dir / "transcript.md":
            raise OSError("boom")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    run = gr.build_run(workspace, run_dir)
    assert run is not None
    assert run["prompt"] == "(プロンプトが見つかりません)"


def test_embed_file_handles_read_bytes_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    pdf_file = tmp_path / "report.pdf"
    pdf_file.write_bytes(b"%PDF")
    xlsx_file = tmp_path / "sheet.xlsx"
    xlsx_file.write_bytes(b"PK\x03\x04")
    binary_file = tmp_path / "blob.bin"
    binary_file.write_bytes(b"binary")

    original_read_bytes = Path.read_bytes

    def fake_read_bytes(self: Path, *args, **kwargs):  # noqa: ANN001
        if self in {image_file, pdf_file, xlsx_file, binary_file}:
            raise OSError("boom")
        return original_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)

    assert gr.embed_file(image_file)["type"] == "error"
    assert gr.embed_file(pdf_file)["type"] == "error"
    assert gr.embed_file(xlsx_file)["type"] == "error"
    assert gr.embed_file(binary_file)["type"] == "error"


def test_load_previous_iteration_handles_corrupt_feedback(tmp_path: Path) -> None:
    workspace, _ = _make_workspace(tmp_path)
    (workspace / "feedback.json").write_text("{bad", encoding="utf-8")

    previous = gr.load_previous_iteration(workspace)

    assert previous["project-run-1"]["feedback"] == ""
    assert previous["project-run-1"]["outputs"]


def test_kill_port_handles_timeout_and_pid_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gr.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(gr.subprocess.TimeoutExpired(cmd="lsof", timeout=5)),
    )
    gr._kill_port(3117)

    monkeypatch.setattr(gr.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="123\nbad\n"))
    monkeypatch.setattr(gr.os, "kill", lambda pid, sig: (_ for _ in ()).throw(ProcessLookupError("gone")))
    monkeypatch.setattr(gr.time, "sleep", lambda seconds: None)
    gr._kill_port(3117)


def test_review_handler_constructor_and_log_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace, _ = _make_workspace(tmp_path)
    feedback_path = workspace / "feedback.json"
    benchmark_path = workspace / "benchmark.json"
    benchmark_path.write_text(json.dumps({"score": 1}), encoding="utf-8")

    monkeypatch.setattr(gr.BaseHTTPRequestHandler, "__init__", lambda self, *args, **kwargs: None)
    handler = gr.ReviewHandler(workspace, "skill-name", feedback_path, {"previous": True}, benchmark_path, object(), ("127.0.0.1", 0), object())

    assert handler.workspace == workspace
    assert handler.skill_name == "skill-name"
    assert handler.feedback_path == feedback_path
    assert handler.previous == {"previous": True}
    assert handler.benchmark_path == benchmark_path
    gr.ReviewHandler.log_message(handler, "%s", "message")


def test_review_handler_missing_feedback_and_invalid_post(tmp_path: Path) -> None:
    workspace, _ = _make_workspace(tmp_path)
    feedback_path = workspace / "feedback.json"
    benchmark_path = workspace / "benchmark.json"
    benchmark_path.write_text("{bad", encoding="utf-8")

    handler, responses, headers, errors, wfile = _make_handler(
        path="/api/feedback",
        workspace=workspace,
        feedback_path=feedback_path,
        previous={},
    )
    gr.ReviewHandler.do_GET(handler)
    assert responses == [200]
    assert wfile.getvalue() == b"{}"

    handler, responses, headers, errors, wfile = _make_handler(
        path="/",
        workspace=workspace,
        feedback_path=feedback_path,
        benchmark_path=benchmark_path,
    )
    gr.ReviewHandler.do_GET(handler)
    assert responses == [200]
    assert ("Content-Type", "text/html; charset=utf-8") in headers

    handler, responses, headers, errors, wfile = _make_handler(
        path="/api/feedback",
        workspace=workspace,
        feedback_path=feedback_path,
        body=b"not-json",
    )
    gr.ReviewHandler.do_POST(handler)
    assert responses == [500]
    assert json.loads(wfile.getvalue())["error"]

    handler, responses, headers, errors, wfile = _make_handler(
        path="/missing",
        workspace=workspace,
        feedback_path=feedback_path,
        body=b"{}",
    )
    gr.ReviewHandler.do_POST(handler)
    assert errors == [404]


def test_main_previous_workspace_and_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    workspace, _ = _make_workspace(tmp_path)
    previous_workspace, _ = _make_workspace(tmp_path / "previous")
    (previous_workspace / "feedback.json").write_text(
        json.dumps({"reviews": [{"run_id": "project-run-1", "feedback": "great"}]}),
        encoding="utf-8",
    )
    benchmark = tmp_path / "benchmark.json"
    benchmark.write_text("{bad", encoding="utf-8")

    class FakeServer:
        def __init__(self, address, handler):  # noqa: ANN001
            self.server_address = (address[0], 4321)
            self._calls = getattr(FakeServer, "_calls", 0)
            FakeServer._calls = self._calls + 1
            if FakeServer._calls == 1:
                raise OSError("busy")

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            self.closed = True

    monkeypatch.setattr(gr, "_kill_port", lambda port: None)
    monkeypatch.setattr(gr, "HTTPServer", FakeServer)
    monkeypatch.setattr(gr.webbrowser, "open", lambda url: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_review.py",
            str(workspace),
            "--previous-workspace",
            str(previous_workspace),
            "--benchmark",
            str(benchmark),
        ],
    )

    gr.main()
    output = capsys.readouterr().out
    assert "前回" in output
    assert "ベンチマーク" in output

    static_path = tmp_path / "entrypoint.html"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_review.py",
            str(workspace),
            "--static",
            str(static_path),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("devgear.skills.eval_viewer.generate_review", run_name="__main__")
    assert excinfo.value.code == 0
