"""Parcel Reality Bench — static leaderboard page (single self-contained HTML file)."""
import html
import json
from pathlib import Path

from .generate import TRAPS

TRAP_LABELS = {
    "price_scale": "Implied-decimal price", "non_arms_length": "Related-party sale",
    "multi_parcel_sale": "Multi-parcel sale", "outlier": "Keying outlier",
    "duplicate_record": "Duplicate record", "cross_jurisdiction_comp": "Cross-border comp",
    "jurisdiction_mismatch": "Jurisdiction inversion",
}


def best_runs(results_dir, split):
    """One row per solver: all of its runs on this split merged, newest answer per item wins.
    (Replaces best-of selection, which overstated scores.)"""
    from .score import summarize
    by_solver = {}
    for p in sorted(Path(results_dir).glob("*.json"), key=lambda q: q.stat().st_mtime):
        r = json.loads(p.read_text())
        if r["split"] != split:
            continue
        m = by_solver.setdefault(r["solver"], {"solver": r["solver"], "split": split, "run_ids": [], "items": {}})
        m["run_ids"].append(r["run_id"])
        for row in r["items"]:
            m["items"][row["id"]] = row
    out = []
    for m in by_solver.values():
        rows = list(m["items"].values())
        out.append({"solver": m["solver"], "split": split, "run_id": ",".join(m["run_ids"]),
                    "items": rows, "summary": summarize([row["scores"] for row in rows])})
    return sorted(out, key=lambda r: -r["summary"]["composite"])


def pct(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}"


def cell(rate):
    if rate is None:
        return '<td class="st na"><span class="g" aria-hidden="true">·</span><span>n/a</span></td>'
    if rate >= 0.8:
        cls, g, lab = "held", "●", "held"
    elif rate >= 0.4:
        cls, g, lab = "part", "◐", "partial"
    else:
        cls, g, lab = "fail", "○", "failed"
    return (f'<td class="st {cls}" title="{lab}"><span class="g" aria-hidden="true">{g}</span>'
            f'<span class="v">{rate * 100:.0f}%</span></td>')


def render(results_dir, split, meta, ledger_head, receipt_count, commitments, out_path, nav=None, current=None):
    runs = best_runs(results_dir, split)
    e = html.escape
    rows, fmap = [], []
    for i, r in enumerate(runs, 1):
        s = r["summary"]
        kind = "baseline" if r["solver"].startswith("baseline:") else "model"
        rows.append(
            f'<tr class="{kind}{" lead" if i == 1 and kind == "model" else ""}">'
            f'<td class="rk">{i:02d}</td><td class="mdl"><code>{e(r["solver"])}</code>'
            f'<span class="kind">{kind}</span></td>'
            f'<td class="num big">{s["composite"] * 100:.1f}</td>'
            f'<td class="num">{pct(s["valuation"])}</td><td class="num">{pct(s["calibration"])}</td>'
            f'<td class="num">{pct(s["exclusion"])}</td><td class="num">{pct(s["flags"])}</td>'
            f'<td class="num">{pct(s["jurisdiction"])}</td>'
            f'<td class="num">{pct(s["median_ape"])}%</td><td class="num">{pct(s["coverage_80"], 0)}%</td>'
            f'<td class="num">{pct(s["parse_rate"], 0)}%</td></tr>')
        fmap.append(f'<tr><td class="mdl"><code>{e(r["solver"])}</code></td>'
                    + "".join(cell(s["traps"][t]["handled_rate"]) for t in TRAPS) + "</tr>")
    trap_heads = "".join(f"<th>{e(TRAP_LABELS[t])}<small>n={meta['trap_counts'][t]}</small></th>" for t in TRAPS)
    commit_rows = "".join(
        f'<div class="kv"><span>{e(c["split"])} key commitment</span><code>{e(c["key_commitment"])}</code></div>'
        for c in commitments)
    nav_html = "".join(f'<a href="{e(href)}"{" aria-current=page" if href == current else ""}>{e(title)}</a>'
                       for title, href in (nav or []))
    page = TEMPLATE
    for k, v in {
        "%%SPLIT%%": e(split), "%%N%%": str(meta["n"]), "%%RUNS%%": str(len(runs)),
        "%%ROWS%%": "".join(rows) or '<tr><td colspan="11">No runs yet.</td></tr>',
        "%%FMAP%%": "".join(fmap), "%%TRAPHEADS%%": trap_heads,
        "%%ITEMSHA%%": e(meta["items_sha256"]), "%%HEAD%%": e(ledger_head),
        "%%RECEIPTS%%": str(receipt_count), "%%COMMITS%%": commit_rows,
        "%%GENV%%": e(meta["generator_version"]), "%%NAV%%": nav_html,
    }.items():
        page = page.replace(k, v)
    Path(out_path).write_text(page)
    return out_path


TEMPLATE = r"""<!doctype html>
<html lang="en" data-spine="obsidian">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Parcel Reality Bench — Leaderboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..125,500..900&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--brass:#b8925a;--brass-dim:#8a6c40;--font-d:"Archivo",sans-serif;--font-b:"Inter",sans-serif;--font-m:"JetBrains Mono",monospace}
[data-spine=obsidian]{--bg:#0e0e0f;--bg2:#151516;--line:#2a2927;--ink:#ece6da;--mute:#8d887e;--held:#cfc6b4;--fail:#d98b6a}
[data-spine=bone]{--bg:#f1ece2;--bg2:#e8e1d4;--line:#cfc6b5;--ink:#1a1917;--mute:#6e685d;--held:#1a1917;--fail:#a4482a}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--ink);font:15px/1.55 var(--font-b);-webkit-font-smoothing:antialiased;transition:background .3s,color .3s}
.wrap{max-width:1240px;margin:0 auto;padding:56px 32px 96px}
header{display:grid;grid-template-columns:1fr auto;gap:24px;align-items:end;border-bottom:1px solid var(--line);padding-bottom:40px}
.eyebrow{font:500 12px/1 var(--font-b);letter-spacing:.18em;text-transform:uppercase;color:var(--brass)}
h1{font:800 clamp(44px,7vw,96px)/.92 var(--font-d);font-stretch:112%;letter-spacing:-.02em;margin:18px 0 20px}
h1 em{font-style:normal;color:var(--brass)}
.lede{max-width:640px;color:var(--mute);font-size:17px}
.lede b{color:var(--ink);font-weight:600}
.spine{background:none;border:1px solid var(--line);color:var(--mute);font:500 12px var(--font-b);letter-spacing:.1em;text-transform:uppercase;padding:10px 14px;cursor:pointer}
.spine:hover{border-color:var(--brass);color:var(--ink)}
.tiers{display:flex;gap:4px;margin-bottom:28px}
.tiers a{font:500 12px var(--font-b);letter-spacing:.1em;text-transform:uppercase;color:var(--mute);text-decoration:none;padding:8px 12px;border:1px solid var(--line)}
.tiers a[aria-current]{color:var(--ink);border-color:var(--brass);box-shadow:inset 0 -2px 0 var(--brass)}
.strip{display:flex;gap:48px;padding:28px 0;border-bottom:1px solid var(--line);flex-wrap:wrap}
.strip div span{display:block;font:500 11px var(--font-b);letter-spacing:.14em;text-transform:uppercase;color:var(--mute)}
.strip div b{font:700 28px var(--font-d);font-variant-numeric:tabular-nums}
h2{font:700 13px var(--font-b);letter-spacing:.16em;text-transform:uppercase;margin:64px 0 8px}
h2+p{color:var(--mute);margin-bottom:24px;max-width:720px}
.tbl{overflow-x:auto;border-top:1px solid var(--ink)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font:500 11px var(--font-b);letter-spacing:.1em;text-transform:uppercase;color:var(--mute);text-align:right;padding:14px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th:nth-child(-n+2){text-align:left}
th small{display:block;letter-spacing:0;text-transform:none;opacity:.7;margin-top:2px}
td{padding:16px 12px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
td.rk{text-align:left;color:var(--mute);font-family:var(--font-m);font-size:12px;width:40px}
td.mdl{text-align:left}
code{font:500 13px var(--font-m)}
.kind{display:inline-block;margin-left:10px;font:500 10px var(--font-b);letter-spacing:.12em;text-transform:uppercase;color:var(--mute);border:1px solid var(--line);padding:2px 6px}
tr.baseline td{color:var(--mute)}
td.big{font:700 22px var(--font-d)}
tr.lead td.big{color:var(--brass)}
tr.lead td.rk{color:var(--brass)}
tr.lead{box-shadow:inset 3px 0 0 var(--brass)}
tr{opacity:0;animation:rise .5s ease forwards}
tr:nth-child(1){animation-delay:.05s}tr:nth-child(2){animation-delay:.1s}tr:nth-child(3){animation-delay:.15s}tr:nth-child(4){animation-delay:.2s}tr:nth-child(5){animation-delay:.25s}tr:nth-child(n+6){animation-delay:.3s}
thead tr{opacity:1;animation:none}
@keyframes rise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
td.st{text-align:center}
td.st .g{font-size:15px;margin-right:6px}
td.st .v{font-size:13px}
td.held{color:var(--held)}
td.part{color:var(--mute)}
td.fail{color:var(--fail)}
td.fail .v{border-bottom:1px dashed var(--fail)}
td.na{color:var(--mute);opacity:.5}
.legend{display:flex;gap:24px;margin-top:14px;font-size:13px;color:var(--mute)}
.legend .fail{color:var(--fail)}
.prov{margin-top:8px;border-top:1px solid var(--ink)}
.kv{display:grid;grid-template-columns:260px 1fr;gap:16px;padding:14px 0;border-bottom:1px solid var(--line)}
.kv span{color:var(--mute);font-size:13px}
.kv code{word-break:break-all;color:var(--ink)}
.kv code.b{color:var(--brass)}
pre{font:13px/1.7 var(--font-m);background:var(--bg2);border:1px solid var(--line);padding:18px 20px;margin-top:20px;overflow-x:auto}
footer{margin-top:80px;padding-top:24px;border-top:1px solid var(--line);display:flex;justify-content:space-between;color:var(--mute);font-size:13px}
footer b{color:var(--ink);font-family:var(--font-d);letter-spacing:.2em}
@media(max-width:720px){.wrap{padding:36px 18px 64px}header{grid-template-columns:1fr}.kv{grid-template-columns:1fr;gap:4px}}
@media(prefers-reduced-motion:reduce){tr{animation:none;opacity:1}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <nav class="tiers">%%NAV%%</nav>
    <div class="eyebrow">Neuruh · Evaluation · %%SPLIT%% split</div>
    <h1>Parcel Reality<br><em>Bench</em></h1>
    <p class="lede">Frontier models versus <b>as-received county records</b> on the Indiana–Michigan line.
    Implied-decimal price layouts, related-party transfers, multi-parcel sales, keying errors, duplicates,
    cross-border comps, and jurisdiction inversions. A human records analyst catches these in seconds.
    This measures whether a model does, and whether its confidence interval is honest.</p>
  </div>
  <button class="spine" onclick="toggle()">Switch spine</button>
</header>

<div class="strip">
  <div><span>Items</span><b>%%N%%</b></div>
  <div><span>Trap classes</span><b>7</b></div>
  <div><span>Solvers ranked</span><b>%%RUNS%%</b></div>
  <div><span>Signed receipts</span><b>%%RECEIPTS%%</b></div>
</div>

<h2>Leaderboard</h2>
<p>Composite = 30% valuation accuracy · 20% interval calibration (Winkler, 80%) · 25% invalid-comp exclusion F1 ·
15% trap-flag F1 · 10% jurisdiction. Baselines are deterministic pipelines, shown for reference.</p>
<div class="tbl"><table>
<thead><tr><th>#</th><th>Solver</th><th>Composite</th><th>Valuation</th><th>Calibration</th><th>Exclusion</th><th>Flags</th><th>Jurisdiction</th><th>Median error</th><th>80% cover</th><th>Parse</th></tr></thead>
<tbody>%%ROWS%%</tbody></table></div>

<h2>Failure map</h2>
<p>Share of items where each trap was correctly handled. This is the part that matters: not whether a model is good,
but exactly where it breaks.</p>
<div class="tbl"><table>
<thead><tr><th>Solver</th>%%TRAPHEADS%%</tr></thead>
<tbody>%%FMAP%%</tbody></table></div>
<div class="legend"><span>● held ≥80%</span><span>◐ partial 40–79%</span><span class="fail">○ failed &lt;40% (dashed)</span></div>

<h2>Provenance</h2>
<p>Every scored answer is a hash-chained receipt. Editing any past result breaks the chain. The holdout key is
committed before any model is run and revealed afterward.</p>
<div class="prov">
  <div class="kv"><span>Dataset (%%SPLIT%%) sha256</span><code>%%ITEMSHA%%</code></div>
  <div class="kv"><span>Ledger head</span><code class="b">%%HEAD%%</code></div>
  %%COMMITS%%
  <div class="kv"><span>Generator</span><code>prbench %%GENV%%</code></div>
</div>
<pre>python3 -m prbench verify     # recompute every hash + re-score every stored response</pre>

<footer><b>NEURUH</b><span>Parcel Reality Bench</span></footer>
</div>
<script>
(function(){var m=window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches;
document.documentElement.dataset.spine=m?'bone':'obsidian';})();
function toggle(){var r=document.documentElement;r.dataset.spine=r.dataset.spine==='bone'?'obsidian':'bone';}
</script>
</body>
</html>
"""
