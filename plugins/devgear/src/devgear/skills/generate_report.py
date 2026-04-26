#!/usr/bin/env python3
"""run_loop.py の出力から HTML レポートを生成する。

run_loop.py の JSON 出力を受け取り、各説明案と各テストケースの
成否を見せるビジュアルな HTML レポートを作成する。
学習用クエリと検証用クエリも分けて表示する。
"""

import argparse
import html
import json
import sys
from pathlib import Path


def generate_html(data: dict, auto_refresh: bool = False, skill_name: str = "") -> str:
    """ループ出力データから HTML レポートを生成する。auto_refresh=True なら meta refresh を付ける。"""
    history = data.get("history", [])
    data.get("holdout", 0)
    title_prefix = html.escape(skill_name + " \u2014 ") if skill_name else ""

    # 学習用・検証用の全クエリを should_trigger 情報付きで集める
    train_queries: list[dict] = []
    test_queries: list[dict] = []
    if history:
        for r in history[0].get("train_results", history[0].get("results", [])):
            train_queries.append({"query": r["query"], "should_trigger": r.get("should_trigger", True)})
        if history[0].get("test_results"):
            for r in history[0].get("test_results", []):
                test_queries.append({"query": r["query"], "should_trigger": r.get("should_trigger", True)})

    refresh_tag = '    <meta http-equiv="refresh" content="5">\n' if auto_refresh else ""

    html_parts = [
        """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
"""
        + refresh_tag
        + """    <title>"""
        + title_prefix
        + """スキル説明の最適化</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@500;600&family=Lora:wght@400;500&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Lora', Georgia, serif;
            max-width: 100%;
            margin: 0 auto;
            padding: 20px;
            background: #faf9f5;
            color: #141413;
        }
        h1 { font-family: 'Poppins', sans-serif; color: #141413; }
        .explainer {
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border: 1px solid #e8e6dc;
            color: #b0aea5;
            font-size: 0.875rem;
            line-height: 1.6;
        }
        .summary {
            background: white;
            padding: 15px;
            border-radius: 6px;
            margin-bottom: 20px;
            border: 1px solid #e8e6dc;
        }
        .summary p { margin: 5px 0; }
        .best { color: #788c5d; font-weight: bold; }
        .table-container {
            overflow-x: auto;
            width: 100%;
        }
        table {
            border-collapse: collapse;
            background: white;
            border: 1px solid #e8e6dc;
            border-radius: 6px;
            font-size: 12px;
            min-width: 100%;
        }
        th, td {
            padding: 8px;
            text-align: left;
            border: 1px solid #e8e6dc;
            white-space: normal;
            word-wrap: break-word;
        }
        th {
            font-family: 'Poppins', sans-serif;
            background: #141413;
            color: #faf9f5;
            font-weight: 500;
        }
        th.test-col {
            background: #6a9bcc;
        }
        th.query-col { min-width: 200px; }
        td.description {
            font-family: monospace;
            font-size: 11px;
            word-wrap: break-word;
            max-width: 400px;
        }
        td.result {
            text-align: center;
            font-size: 16px;
            min-width: 40px;
        }
        td.test-result {
            background: #f0f6fc;
        }
        .pass { color: #788c5d; }
        .fail { color: #c44; }
        .rate {
            font-size: 9px;
            color: #b0aea5;
            display: block;
        }
        tr:hover { background: #faf9f5; }
        .score {
            display: inline-block;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: bold;
            font-size: 11px;
        }
        .score-good { background: #eef2e8; color: #788c5d; }
        .score-ok { background: #fef3c7; color: #d97706; }
        .score-bad { background: #fceaea; color: #c44; }
        .train-label { color: #b0aea5; font-size: 10px; }
        .test-label { color: #6a9bcc; font-size: 10px; font-weight: bold; }
        .best-row { background: #f5f8f2; }
        th.positive-col { border-bottom: 3px solid #788c5d; }
        th.negative-col { border-bottom: 3px solid #c44; }
        th.test-col.positive-col { border-bottom: 3px solid #788c5d; }
        th.test-col.negative-col { border-bottom: 3px solid #c44; }
        .legend { font-family: 'Poppins', sans-serif; display: flex; gap: 20px; margin-bottom: 10px; font-size: 13px; align-items: center; }
        .legend-item { display: flex; align-items: center; gap: 6px; }
        .legend-swatch { width: 16px; height: 16px; border-radius: 3px; display: inline-block; }
        .swatch-positive { background: #141413; border-bottom: 3px solid #788c5d; }
        .swatch-negative { background: #141413; border-bottom: 3px solid #c44; }
        .swatch-test { background: #6a9bcc; }
        .swatch-train { background: #141413; }
    </style>
</head>
<body>
    <h1>"""
        + title_prefix
        + """スキル説明の最適化</h1>
    <div class="explainer">
        <strong>スキル説明を最適化しています。</strong> このページは、Claude がスキル説明の各版を試すたびに自動更新されます。各行は 1 回の反復（新しい説明案）です。列はテストクエリを表し、緑のチェックはスキルが正しくトリガーされた（または正しくトリガーされなかった）こと、赤い×は誤ったことを示します。「学習用」スコアは説明改善に使ったクエリでの成績、「検証用」スコアは最適化側が見ていない保留クエリでの成績です。完了すると、Claude は最も成績の良かった説明をスキルに適用します。
    </div>
"""
    ]

    # サマリーセクション
    best_test_score = data.get("best_test_score")
    data.get("best_train_score")
    html_parts.append(f"""
    <div class="summary">
        <p><strong>元の説明:</strong> {html.escape(data.get("original_description", "N/A"))}</p>
        <p class="best"><strong>最良の説明:</strong> {html.escape(data.get("best_description", "N/A"))}</p>
        <p><strong>最良スコア:</strong> {data.get("best_score", "N/A")} {"(検証用)" if best_test_score else "(学習用)"}</p>
        <p><strong>反復回数:</strong> {data.get("iterations_run", 0)} | <strong>学習用:</strong> {data.get("train_size", "?")} | <strong>検証用:</strong> {data.get("test_size", "?")}</p>
    </div>
""")

    # Legend
    html_parts.append("""
    <div class="legend">
        <span style="font-weight:600">クエリ列:</span>
        <span class="legend-item"><span class="legend-swatch swatch-positive"></span> トリガーすべき</span>
        <span class="legend-item"><span class="legend-swatch swatch-negative"></span> トリガーすべきでない</span>
        <span class="legend-item"><span class="legend-swatch swatch-train"></span> 学習用</span>
        <span class="legend-item"><span class="legend-swatch swatch-test"></span> 検証用</span>
    </div>
""")

    # Table header
    html_parts.append("""
    <div class="table-container">
    <table>
        <thead>
            <tr>
                <th>反復</th>
                <th>学習</th>
                <th>検証</th>
                <th class="query-col">説明</th>
""")

    # Add column headers for train queries
    for qinfo in train_queries:
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        html_parts.append(f'                <th class="{polarity}">{html.escape(qinfo["query"])}</th>\n')

    # Add column headers for test queries (different color)
    for qinfo in test_queries:
        polarity = "positive-col" if qinfo["should_trigger"] else "negative-col"
        html_parts.append(f'                <th class="test-col {polarity}">{html.escape(qinfo["query"])}</th>\n')

    html_parts.append("""            </tr>
        </thead>
        <tbody>
""")

    # Find best iteration for highlighting
    if test_queries:
        best_iter = max(history, key=lambda h: h.get("test_passed") or 0).get("iteration")
    else:
        best_iter = max(history, key=lambda h: h.get("train_passed", h.get("passed", 0))).get("iteration")

    # Add rows for each iteration
    for h in history:
        iteration = h.get("iteration", "?")
        h.get("train_passed", h.get("passed", 0))
        h.get("train_total", h.get("total", 0))
        h.get("test_passed")
        h.get("test_total")
        description = h.get("description", "")
        train_results = h.get("train_results", h.get("results", []))
        test_results = h.get("test_results", [])

        # Create lookups for results by query
        train_by_query = {r["query"]: r for r in train_results}
        test_by_query = {r["query"]: r for r in test_results} if test_results else {}

        # Compute aggregate correct/total runs across all retries
        def aggregate_runs(results: list[dict]) -> tuple[int, int]:
            correct = 0
            total = 0
            for r in results:
                runs = r.get("runs", 0)
                triggers = r.get("triggers", 0)
                total += runs
                if r.get("should_trigger", True):
                    correct += triggers
                else:
                    correct += runs - triggers
            return correct, total

        train_correct, train_runs = aggregate_runs(train_results)
        test_correct, test_runs = aggregate_runs(test_results)

        # Determine score classes
        def score_class(correct: int, total: int) -> str:
            if total > 0:
                ratio = correct / total
                if ratio >= 0.8:
                    return "score-good"
                elif ratio >= 0.5:
                    return "score-ok"
            return "score-bad"

        train_class = score_class(train_correct, train_runs)
        test_class = score_class(test_correct, test_runs)

        row_class = "best-row" if iteration == best_iter else ""

        html_parts.append(f"""            <tr class="{row_class}">
                <td>{iteration}</td>
                <td><span class="score {train_class}">{train_correct}/{train_runs}</span></td>
                <td><span class="score {test_class}">{test_correct}/{test_runs}</span></td>
                <td class="description">{html.escape(description)}</td>
""")

        # Add result for each train query
        for qinfo in train_queries:
            r = train_by_query.get(qinfo["query"], {})
            did_pass = r.get("pass", False)
            triggers = r.get("triggers", 0)
            runs = r.get("runs", 0)

            icon = "✓" if did_pass else "✗"
            css_class = "pass" if did_pass else "fail"

            html_parts.append(
                f'                <td class="result {css_class}">{icon}<span class="rate">{triggers}/{runs}</span></td>\n'
            )

        # Add result for each test query (with different background)
        for qinfo in test_queries:
            r = test_by_query.get(qinfo["query"], {})
            did_pass = r.get("pass", False)
            triggers = r.get("triggers", 0)
            runs = r.get("runs", 0)

            icon = "✓" if did_pass else "✗"
            css_class = "pass" if did_pass else "fail"

            html_parts.append(
                f'                <td class="result test-result {css_class}">{icon}<span class="rate">{triggers}/{runs}</span></td>\n'
            )

        html_parts.append("            </tr>\n")

    html_parts.append("""        </tbody>
    </table>
    </div>
""")

    html_parts.append("""
</body>
</html>
""")

    return "".join(html_parts)


def main():
    parser = argparse.ArgumentParser(description="run_loop の出力から HTML レポートを生成する")
    parser.add_argument("input", help="run_loop.py の JSON 出力へのパス（または stdin の場合は -）")
    parser.add_argument("-o", "--output", default=None, help="出力する HTML ファイル（既定: stdout）")
    parser.add_argument("--skill-name", default="", help="レポートタイトルに含めるスキル名")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(args.input).read_text())

    html_output = generate_html(data, skill_name=args.skill_name)

    if args.output:
        Path(args.output).write_text(html_output)
        print(f"レポートを書き出しました: {args.output}", file=sys.stderr)
    else:
        print(html_output)


if __name__ == "__main__":
    main()
