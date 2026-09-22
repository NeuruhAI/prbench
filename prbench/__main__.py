"""Parcel Reality Bench CLI.

  python3 -m prbench generate                      # build public + holdout splits
  python3 -m prbench commit --salt "<secret>"      # publish holdout commitment
  python3 -m prbench run --solver rules            # offline baseline
  python3 -m prbench run --solver anthropic:claude-sonnet-5 --limit 10
  python3 -m prbench verify                        # chain + re-score everything
  python3 -m prbench leaderboard                   # write leaderboard.html
  python3 -m prbench auto                          # discover new models, run, verify, publish, draft
"""
import argparse
import json
import secrets
import sys
import time
from pathlib import Path

from . import generate as gen
from .discover import discover, save_state
from .generate import TRAPS
from .leaderboard import render
from .receipts import Ledger, commit_split, sha, verify_chain
from .score import extract_json, score_item, summarize
from .solvers import get_solver

ROOT = Path.cwd()
DATA, RESULTS, LEDGER = ROOT / "data", ROOT / "results", ROOT / "receipts" / "ledger.jsonl"
COMMITS = ROOT / "receipts" / "commitments.json"
STATE = ROOT / "receipts" / "models_seen.json"
DRAFTS = ROOT / "drafts"


def load_split(split):
    d = DATA / split
    if not (d / "items.jsonl").exists():
        sys.exit(f"No data for split '{split}'. Run: python3 -m prbench generate")
    items = [json.loads(l) for l in (d / "items.jsonl").read_text().splitlines() if l.strip()]
    keys = {}
    if (d / "key.jsonl").exists():
        keys = {k["id"]: k for k in (json.loads(l) for l in (d / "key.jsonl").read_text().splitlines() if l.strip())}
    return items, keys, json.loads((d / "meta.json").read_text())


def cmd_generate(a):
    hseed = a.holdout_seed or secrets.token_hex(16)
    for split, n, seed in (("public", a.public_n, a.public_seed),
                           ("holdout", a.holdout_n, hseed),
                           ("public_hard", a.public_n, a.public_seed),
                           ("holdout_hard", a.holdout_n, hseed)):
        meta = gen.generate_split(DATA, split, n, seed)
        print(f"[{split}] {n} items  items_sha256={meta['items_sha256'][:16]}…  traps={meta['trap_counts']}")
    print("Holdout seed is random unless --holdout-seed was given. Keep data/holdout/key.jsonl private.")


def cmd_commit(a):
    existing = json.loads(COMMITS.read_text()) if COMMITS.exists() else []
    COMMITS.parent.mkdir(parents=True, exist_ok=True)
    for split in ("holdout", "holdout_hard"):
        c = commit_split(DATA / split, a.salt)
        existing = [x for x in existing if x["split"] != c["split"]] + [c]
        Ledger(LEDGER).append({"type": "commitment", **c})
        print(json.dumps(c, indent=2))
    COMMITS.write_text(json.dumps(existing, indent=2))
    print("Publish the key_commitment values above before running any model on a holdout.")
    print("\nStore the salt somewhere safe. Revealing salt + key.jsonl later proves you did not move the goalposts.")


def run_split(solver, split, limit=0, sleep=0.0, quiet=False):
    items, keys, meta = load_split(split)
    if not keys:
        raise SystemExit(f"Answer key missing for split '{split}'; cannot score.")
    label, solve = get_solver(solver)
    items = items[:limit] if limit else items
    ledger = Ledger(LEDGER)
    run_id = f"{time.strftime('%Y%m%dT%H%M%S')}-{split}-{label.replace(':', '_').replace('/', '_')}"
    rows, scored = [], []
    for i, item in enumerate(items, 1):
        key = keys[item["id"]]
        raw = solve(item, key)
        ans = None if raw.startswith("__ERROR__") else extract_json(raw)
        s = score_item(ans, key)
        scored.append(s)
        rows.append({"id": item["id"], "response": raw, "scores": s})
        ledger.append({"type": "score", "run_id": run_id, "solver": label, "item": item["id"],
                       "prompt_sha256": sha(item["prompt"]), "response_sha256": sha(raw),
                       "composite": round(s["composite"], 6)})
        if not quiet:
            err = "  ERR " + raw[:90] if raw.startswith("__ERROR__") else ""
            print(f"  {i:>4}/{len(items)} {item['id']}  composite={s['composite']:.3f}{err}", flush=True)
        if sleep:
            time.sleep(sleep)
    summary = summarize(scored)
    result = {"run_id": run_id, "solver": label, "split": split, "items_sha256": meta["items_sha256"],
              "summary": summary, "items": rows}
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{run_id}.json"
    out.write_text(json.dumps(result, indent=1))
    seal = ledger.append({"type": "run_seal", "run_id": run_id, "solver": label, "split": split,
                          "n": len(rows), "result_sha256": sha(json.dumps(summary, sort_keys=True)),
                          "composite": round(summary["composite"], 6)})
    return label, summary, out, seal


def print_summary(label, summary):
    print(f"{label}  composite={summary['composite'] * 100:.1f}  valuation={summary['valuation'] * 100:.1f}  "
          f"calibration={summary['calibration'] * 100:.1f}  exclusion={summary['exclusion'] * 100:.1f}  "
          f"jurisdiction={summary['jurisdiction'] * 100:.1f}")
    for t, v in summary["traps"].items():
        if v["n"]:
            print(f"    {t:<26} handled {v['handled_rate'] * 100:5.1f}%  (n={v['n']})")


def cmd_run(a):
    label, summary, out, seal = run_split(a.solver, a.split, a.limit, a.sleep)
    print()
    print_summary(label, summary)
    print(f"\nresults: {out}\nreceipt: seq {seal['seq']}  {seal['hash'][:24]}…")


def verify_all():
    if not LEDGER.exists():
        return False, ["No ledger yet."], 0, 0
    n, head, problems = verify_chain(LEDGER)
    receipts = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    by_key = {(r["run_id"], r["item"]): r for r in receipts if r.get("type") == "score"}
    rescored = mismatched = 0
    for p in sorted(RESULTS.glob("*.json")):
        res = json.loads(p.read_text())
        _, keys, _ = load_split(res["split"])
        for row in res["items"]:
            rec = by_key.get((res["run_id"], row["id"]))
            if rec is None:
                problems.append(f"{p.name} {row['id']}: no receipt")
                continue
            if sha(row["response"]) != rec["response_sha256"]:
                problems.append(f"{p.name} {row['id']}: stored response does not match receipt")
            if keys:
                raw = row["response"]
                s = score_item(None if raw.startswith("__ERROR__") else extract_json(raw), keys[row["id"]])
                rescored += 1
                if abs(s["composite"] - rec["composite"]) > 1e-5:
                    mismatched += 1
                    problems.append(f"{p.name} {row['id']}: re-score {s['composite']:.6f} != receipt {rec['composite']}")
    print(f"receipts: {n}   head: {head}\nre-scored responses: {rescored}   score mismatches: {mismatched}")
    return not problems, problems, n, rescored


def cmd_verify(a):
    ok, problems, _, _ = verify_all()
    if not ok:
        print("FAIL")
        for x in problems[:50]:
            print("  -", x)
        sys.exit(1)
    print("PASS — chain intact, every stored response hashes to its receipt, every score reproduces.")


SPLIT_TITLES = {"public_hard": "Hard", "public": "Standard", "holdout_hard": "Holdout · Hard", "holdout": "Holdout"}


def build_site(splits, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    n, head, _ = verify_chain(LEDGER) if LEDGER.exists() else (0, "—", [])
    commits = json.loads(COMMITS.read_text()) if COMMITS.exists() else []
    nav = [(SPLIT_TITLES.get(sp, sp), "index.html" if i == 0 else f"{sp}.html") for i, sp in enumerate(splits)]
    written = []
    for i, sp in enumerate(splits):
        if not (DATA / sp / "meta.json").exists():
            continue
        _, _, meta = load_split(sp)
        fname = "index.html" if i == 0 else f"{sp}.html"
        render(RESULTS, sp, meta, head, n, commits, out_dir / fname, nav=nav, current=fname)
        written.append(out_dir / fname)
    return written


def cmd_leaderboard(a):
    _, _, meta = load_split(a.split)
    n, head, _ = verify_chain(LEDGER) if LEDGER.exists() else (0, "—", [])
    commits = json.loads(COMMITS.read_text()) if COMMITS.exists() else []
    out = render(RESULTS, a.split, meta, head, n, commits, a.out)
    print(f"wrote {out}")


def saturation_report(split, threshold):
    """Recursive loop: traps every real model clears get flagged so the next generator version hardens them."""
    runs = [json.loads(p.read_text()) for p in RESULTS.glob("*.json")]
    models = {}
    for r in runs:
        if r["split"] == split and not r["solver"].startswith("baseline:"):
            if r["solver"] not in models or r["summary"]["composite"] > models[r["solver"]]["composite"]:
                models[r["solver"]] = r["summary"]
    if not models:
        return None
    lines = [f"# Saturation report — {split}", "", f"Models: {len(models)}. Threshold: {threshold:.0%}.", ""]
    for t in TRAPS:
        rates = [m["traps"][t]["handled_rate"] for m in models.values() if m["traps"][t]["handled_rate"] is not None]
        if not rates:
            continue
        worst = min(rates)
        status = "SATURATED — harden in next generator version" if worst >= threshold else "discriminating"
        lines.append(f"- {t}: min {worst:.0%}, max {max(rates):.0%} — {status}")
    best = max(m["composite"] for m in models.values())
    lines += ["", f"Best composite: {best * 100:.1f}. " +
              ("Bench saturating: ship next difficulty tier." if best >= threshold else "Headroom remains.")]
    return "\n".join(lines)


def announcement(spec, summaries, baseline):
    hard = summaries.get("public_hard") or next(iter(summaries.values()))
    traps = sorted(((v["handled_rate"], t) for t, v in hard["traps"].items() if v["handled_rate"] is not None))
    worst = [f"{t.replace('_', ' ')} {r * 100:.0f}%" for r, t in traps[:2]]
    rows = "\n".join(f"| {sp} | {s['composite'] * 100:.1f} | {s['median_ape'] * 100 if s['median_ape'] is not None else float('nan'):.1f}% "
                     f"| {s['coverage_80'] * 100:.0f}% | {s['parse_rate'] * 100:.0f}% |" for sp, s in summaries.items())
    base = f"{baseline * 100:.1f}" if baseline is not None else "n/a"
    post = (f"{spec.split(':', 1)[1]} on Parcel Reality Bench (hard): {hard['composite'] * 100:.1f}. "
            f"a deterministic records pipeline scores {base}. weakest traps: {', '.join(worst)}. "
            f"every answer hash-chained, holdout committed in advance. [LEADERBOARD_URL]")
    return (f"# {spec} — benchmarked {time.strftime('%Y-%m-%d')}\n\n"
            f"| split | composite | median error | 80% coverage | parse |\n|---|---|---|---|---|\n{rows}\n\n"
            f"## Draft post (review before sending; nothing is posted automatically)\n\n{post}\n")


def baseline_composite(split, solver):
    for p in sorted(RESULTS.glob("*.json"), reverse=True):
        r = json.loads(p.read_text())
        if r["split"] == split and r["solver"] == solver:
            return r["summary"]["composite"]
    return None


def ensure_baselines(splits):
    """Offline baselines are free; make sure every published tier has them before models are ranked."""
    for sp in splits:
        if not (DATA / sp / "key.jsonl").exists():
            continue
        for b in ("rules", "naive"):
            if baseline_composite(sp, f"baseline:{b}") is None:
                label, summ, _, _ = run_split(b, sp, quiet=True)
                print(f"[baseline] {label} on {sp}: {summ['composite'] * 100:.1f}")


def cmd_auto(a):
    cfg = json.loads(Path(a.config).read_text())
    if not a.dry_run and not a.bootstrap:
        ensure_baselines(cfg["splits"])
    queue, state, log = discover(cfg, STATE)
    for line in log:
        print("[discover]", line)
    if a.bootstrap:
        for spec, v in state.items():
            if not v.get("pinned") and not v["benchmarked"]:
                v.update(benchmarked=True, skipped="bootstrap")
        save_state(state, STATE)
        print(f"[bootstrap] marked existing models as seen. Pinned models queued: "
              f"{[s for s, v in state.items() if not v['benchmarked']]}")
        return
    save_state(state, STATE)
    print(f"[queue] {queue or 'nothing new'}")
    if a.dry_run:
        return
    DRAFTS.mkdir(exist_ok=True)
    for spec in queue:
        summaries = {}
        for sp in cfg["splits"]:
            if not (DATA / sp / "key.jsonl").exists():
                print(f"[run] {spec} {sp}: no key on this machine, skipped")
                continue
            print(f"[run] {spec} on {sp} ...", flush=True)
            label, summ, out, _ = run_split(spec, sp, sleep=cfg.get("sleep_seconds", 0), quiet=True)
            summaries[sp] = summ
            print(f"      composite {summ['composite'] * 100:.1f}  parse {summ['parse_rate'] * 100:.0f}%")
        state[spec].update(benchmarked=True, benchmarked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           composite={k: round(v["composite"], 4) for k, v in summaries.items()})
        if summaries and max(v["parse_rate"] for v in summaries.values()) == 0:
            state[spec]["unusable"] = True  # e.g. a non-chat model that slipped through filters
            print(f"      {spec} returned nothing parseable; marked unusable, no announcement")
        elif summaries:
            base = baseline_composite("public_hard", "baseline:rules")
            path = DRAFTS / f"{time.strftime('%Y%m%d')}-{spec.replace(':', '_').replace('/', '_')}.md"
            path.write_text(announcement(spec, summaries, base))
            print(f"      draft: {path}")
        save_state(state, STATE)
    ok, problems, n, rescored = verify_all()
    if not ok:
        print("[verify] FAIL — site not rebuilt")
        for x in problems[:20]:
            print("  -", x)
        sys.exit(1)
    print("[verify] PASS")
    for p in build_site(cfg["publish_splits"], a.site):
        print(f"[site] {p}")
    rep = saturation_report(cfg["publish_splits"][0], cfg.get("saturation_threshold", 0.95))
    if rep:
        (DRAFTS / "saturation.md").write_text(rep)
        print(f"[saturation] {DRAFTS / 'saturation.md'}")


def main():
    ap = argparse.ArgumentParser(prog="prbench", description="Parcel Reality Bench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--public-n", type=int, default=60)
    g.add_argument("--public-seed", default="2026")
    g.add_argument("--holdout-n", type=int, default=200)
    g.add_argument("--holdout-seed", default=None)
    c = sub.add_parser("commit")
    c.add_argument("--salt", required=True)
    r = sub.add_parser("run")
    r.add_argument("--solver", required=True)
    r.add_argument("--split", default="public")
    r.add_argument("--limit", type=int, default=0)
    r.add_argument("--sleep", type=float, default=0.0)
    sub.add_parser("verify")
    lb = sub.add_parser("leaderboard")
    lb.add_argument("--split", default="public")
    lb.add_argument("--out", default="leaderboard.html")
    au = sub.add_parser("auto")
    au.add_argument("--config", default="bench.config.json")
    au.add_argument("--site", default="site")
    au.add_argument("--dry-run", action="store_true")
    au.add_argument("--bootstrap", action="store_true")
    a = ap.parse_args()
    {"generate": cmd_generate, "commit": cmd_commit, "run": cmd_run,
     "verify": cmd_verify, "leaderboard": cmd_leaderboard, "auto": cmd_auto}[a.cmd](a)


if __name__ == "__main__":
    main()
