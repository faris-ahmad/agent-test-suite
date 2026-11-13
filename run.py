"""Run the test cases in cases.yaml against a support agent and write a report.

    python3 run.py                  # scripted demo agent, no API key needed
    python3 run.py --agent claude   # the same tests against Claude

Exit code 0 means there are no new failures. Cases tagged with a known_issue
are reported but do not fail the run, so CI only goes red on a regression.
"""

import argparse
import html
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


# ----------------------------------------------------------------- checks
def run_check(kind, expected, answer):
    """Return None if the check passes, or a sentence saying why it failed."""
    text = answer.lower()
    if kind == "contains_any":
        if not any(p.lower() in text for p in expected):
            return "Expected one of: " + ", ".join(f'"{p}"' for p in expected)
    elif kind == "contains_all":
        missing = [p for p in expected if p.lower() not in text]
        if missing:
            return "Missing: " + ", ".join(f'"{p}"' for p in missing)
    elif kind == "not_contains":
        found = [p for p in expected if p.lower() in text]
        if found:
            return "Must not say: " + ", ".join(f'"{p}"' for p in found)
    elif kind == "max_words":
        words = len(answer.split())
        if words > expected:
            return f"Too long: {words} words, limit is {expected}"
    else:
        return f"Unknown check type: {kind}"
    return None


def run_case(case, ask):
    """Ask the question (several times if `repeat` is set) and check every answer."""
    attempts = []
    for n in range(1, case.get("repeat", 1) + 1):
        answer = ask(case["question"], n)
        problems = []
        for check in case["checks"]:
            for kind, expected in check.items():
                problem = run_check(kind, expected, answer)
                if problem:
                    problems.append(problem)
        attempts.append({"attempt": n, "answer": answer, "problems": problems})

    failed = any(a["problems"] for a in attempts)
    known = case.get("known_issue")
    if not failed:
        status = "fixed" if known else "pass"
    else:
        status = "known" if known else "fail"
    return {**{k: case.get(k) for k in ("id", "category", "title", "question", "known_issue")},
            "status": status, "attempts": attempts}


# ----------------------------------------------------------------- report
LABEL = {"pass": "Pass", "fail": "New failure", "known": "Known issue", "fixed": "Now passing"}


def write_report(results, agent_name, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {s: sum(r["status"] == s for r in results) for s in LABEL}
    (out_dir / "results.json").write_text(json.dumps(
        {"agent": agent_name, "counts": counts, "results": results}, indent=2))

    e = html.escape
    rows = []
    for r in results:
        detail = []
        for a in r["attempts"]:
            tag = f"Attempt {a['attempt']}: " if len(r["attempts"]) > 1 else ""
            detail.append(f"<p class='ans'><b>{tag}Answer:</b> {e(a['answer'])}</p>")
            detail.extend(f"<p class='why'>{e(p)}</p>" for p in a["problems"])
        bug = f" <span class='bug'>{e(r['known_issue'])}</span>" if r["known_issue"] else ""
        rows.append(
            f"<details class='{r['status']}'><summary><span class='id'>{e(r['id'])}</span>"
            f"<span class='cat'>{e(r['category'])}</span><span class='ttl'>{e(r['title'])}{bug}</span>"
            f"<span class='chip'>{LABEL[r['status']]}</span></summary>"
            f"<div class='body'><p><b>Question:</b> {e(r['question'])}</p>{''.join(detail)}</div></details>")

    cards = "".join(
        f"<div class='card {s}'><div class='n'>{counts[s]}</div><div>{LABEL[s]}</div></div>"
        for s in ("pass", "known", "fail", "fixed"))
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent test report</title>
<style>
:root {{ --ink:#1c2326; --muted:#5d6b70; --line:#dfe6e8; --bg:#f6f8f9; --card:#fff;
  --pass:#1f7a4d; --known:#a15c00; --fail:#b3261e; --fixed:#2456a6; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif; }}
main {{ max-width:920px; margin:0 auto; padding:32px 16px 48px; }}
h1 {{ font-size:24px; margin:0 0 4px; }}
.sub {{ color:var(--muted); margin:0 0 24px; }}
.cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:24px; }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; color:var(--muted); }}
.card .n {{ font-size:28px; font-weight:700; }}
.card.pass .n {{ color:var(--pass); }} .card.known .n {{ color:var(--known); }}
.card.fail .n {{ color:var(--fail); }} .card.fixed .n {{ color:var(--fixed); }}
details {{ background:var(--card); border:1px solid var(--line); border-radius:8px; margin-bottom:6px; }}
summary {{ display:grid; grid-template-columns:70px 130px 1fr auto; gap:10px; align-items:center; padding:10px 14px; cursor:pointer; list-style:none; }}
summary::-webkit-details-marker {{ display:none; }}
.id {{ font-weight:600; font-variant-numeric:tabular-nums; }} .cat {{ color:var(--muted); }}
.chip {{ font-size:12px; font-weight:600; padding:2px 10px; border-radius:99px; white-space:nowrap; }}
.pass .chip {{ color:var(--pass); background:#e5f4ec; }} .known .chip {{ color:var(--known); background:#fbefdc; }}
.fail .chip {{ color:var(--fail); background:#fbe6e4; }} .fixed .chip {{ color:var(--fixed); background:#e4ecfa; }}
.bug {{ font-size:12px; color:var(--known); border:1px solid #ecd2a8; border-radius:4px; padding:0 5px; margin-left:6px; }}
.body {{ padding:4px 14px 12px; border-top:1px solid var(--line); }}
.body p {{ margin:8px 0 0; }} .why {{ color:var(--fail); }}
@media (max-width:640px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }} summary {{ grid-template-columns:60px 1fr auto; }} .cat {{ display:none; }} }}
</style><main>
<h1>Agent test report</h1>
<p class="sub">Agent: {e(agent_name)} · {len(results)} test cases · {datetime.now():%d %b %Y, %H:%M}</p>
<div class="cards">{cards}</div>
{''.join(rows)}
</main></html>"""
    (out_dir / "report.html").write_text(page)
    return counts


# ------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description="Test a support agent against cases.yaml")
    parser.add_argument("--agent", default="demo", choices=["demo", "claude"])
    parser.add_argument("--cases", default=str(ROOT / "cases.yaml"))
    parser.add_argument("--out", default=str(ROOT / "report"))
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    ask = importlib.import_module(f"agents.{args.agent}_agent").answer
    cases = yaml.safe_load(Path(args.cases).read_text())

    results = []
    for case in cases:
        result = run_case(case, ask)
        results.append(result)
        bug = f" ({result['known_issue']})" if result["known_issue"] else ""
        print(f"{LABEL[result['status']]:<12} {result['id']:<7} {result['title']}{bug}")

    counts = write_report(results, args.agent, Path(args.out))
    print(f"\n{counts['pass']} passed, {counts['known']} known issues, "
          f"{counts['fail']} new failures, {counts['fixed']} now passing")
    print(f"Report: {Path(args.out) / 'report.html'}")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
