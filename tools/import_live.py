"""Import a claude.ai live-runner result file into the main prbench ledger.

Refuses unless: the file's own receipt chain is intact, it was run on the exact
same dataset (items_sha256), every response hashes to its receipt, and every
score re-computes to the same number with the local scorer.
Usage: python3 tools/import_live.py ~/Downloads/live-XXXX.json
"""
import json, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from prbench.receipts import Ledger, verify_chain, sha, canon
from prbench.score import score_item, summarize, extract_json

ROOT = Path(__file__).resolve().parents[1]
LEDGER, RESULTS = ROOT / "receipts" / "ledger.jsonl", ROOT / "results"

src = Path(sys.argv[1]).expanduser()
live = json.loads(src.read_text())
run_id, split = live["run_id"], live["split"]

tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
tmp.write("\n".join(canon(r) for r in live["receipts"]) + "\n"); tmp.close()
n, head, problems = verify_chain(tmp.name)
if problems: sys.exit(f"STOP: live file chain broken: {problems[:3]}")

meta = json.loads((ROOT / "data" / split / "meta.json").read_text())
if meta["items_sha256"] != live["items_sha256"]:
    sys.exit(f"STOP: dataset mismatch. file={live['items_sha256'][:12]} local={meta['items_sha256'][:12]}")
items = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data" / split / "items.jsonl").read_text().splitlines() if l.strip()}
keys = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "data" / split / "key.jsonl").read_text().splitlines() if l.strip()}

if LEDGER.exists() and any(json.loads(l).get("run_id") == run_id for l in LEDGER.read_text().splitlines() if l.strip()):
    sys.exit(f"STOP: {run_id} is already in the ledger. Nothing changed.")

rec = {r["item"]: r for r in live["receipts"] if r.get("type") == "score"}
rows, scored = [], []
for it in live["items"]:
    r = rec[it["id"]]
    if r["prompt_sha256"] != sha(items[it["id"]]["prompt"]): sys.exit(f"STOP: {it['id']} prompt hash mismatch")
    if r["response_sha256"] != sha(it["response"]): sys.exit(f"STOP: {it['id']} response hash mismatch")
    s = score_item(extract_json(it["response"]), keys[it["id"]])
    if abs(s["composite"] - r["composite"]) > 1e-5: sys.exit(f"STOP: {it['id']} re-score {s['composite']:.6f} != {r['composite']}")
    scored.append(s); rows.append({"id": it["id"], "response": it["response"], "scores": s})

L = Ledger(LEDGER)
for it in live["items"]:
    r = rec[it["id"]]
    L.append({"type": "score", "run_id": run_id, "solver": live["solver"], "item": it["id"],
              "prompt_sha256": r["prompt_sha256"], "response_sha256": r["response_sha256"],
              "composite": r["composite"], "source": "claude.ai live runner", "source_receipt": r["hash"]})
summary = summarize(scored)
RESULTS.mkdir(exist_ok=True)
(RESULTS / f"{run_id}.json").write_text(json.dumps({"run_id": run_id, "solver": live["solver"], "split": split,
    "items_sha256": live["items_sha256"], "summary": summary, "items": rows}, indent=1))
seal = L.append({"type": "run_seal", "run_id": run_id, "solver": live["solver"], "split": split, "n": len(rows),
                 "result_sha256": sha(json.dumps(summary, sort_keys=True)), "composite": round(summary["composite"], 6),
                 "source_chain_head": head})
print(f"PASS: imported {run_id}  n={len(rows)}  composite={summary['composite']*100:.1f}  ledger seq {seal['seq']}")
