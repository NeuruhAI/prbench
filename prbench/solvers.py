"""Parcel Reality Bench — solvers.

Offline baselines (no API key needed):
  oracle  - reads the answer key; sanity check, must score ~1.0
  naive   - takes every record at face value; shows what the traps cost
  rules   - deterministic records pipeline; the "code beats vibes" baseline
Live model adapters (stdlib urllib, no pip installs):
  anthropic:<model>  openai:<model>  gemini:<model>
"""
import json
import os
import re
import statistics
import time
import urllib.error
import urllib.request

from .generate import MARKETS, TOWNS

IN_RE = re.compile(r"^(\d{2})-\d{2}-\d{2}-\d{3}-\d{3}\.\d{3}-\d{3}$")
MI_RE = re.compile(r"^(\d{2})-\d{2}-\d{4}-\d{4}-\d{2}-\d$")
CODE_TO_MKT = {(m["state"], m["code"]): k for k, m in MARKETS.items()}
TOWN_TO_MKT = {(t, k[:2]): k for k, towns in TOWNS.items() for t in towns}
COMP_RE = re.compile(r"^\s+(C\d+) \[src=([^\]]+)\] (.*)$")


# ---------- packet parsing (shared by naive + rules) ----------
def parse_packet(prompt):
    subj, comps, section = {}, [], None
    for line in prompt.splitlines():
        s = line.strip()
        if s == "SUBJECT":
            section = "s"
            continue
        if s.startswith("COMPARABLE SALE RECORDS"):
            section = "c"
            continue
        if s == "TASK":
            break
        if section == "s" and ":" in s:
            k, v = s.split(":", 1)
            subj[k.strip()] = v.strip()
        m = COMP_RE.match(line)
        if section == "c" and m:
            fields = dict(kv.split("=", 1) for kv in m.group(3).split(" | "))
            fields.update(id=m.group(1), src=m.group(2))
            comps.append(fields)
    return subj, comps


def to_num(s):
    return float(re.sub(r"[^\d.]", "", s))


def parcel_market(parcel):
    """IN state parcel numbers carry 18 digits, MI (Berrien/Cass) 15; first two digits are the county code."""
    digits = re.sub(r"\D", "", parcel)
    state = {18: "IN", 15: "MI"}.get(len(digits))
    return CODE_TO_MKT.get((state, digits[:2])) if state else None


def mailing_market(addr):
    parts = [p.strip() for p in addr.split(",")]
    return TOWN_TO_MKT.get((parts[-2], parts[-1])) if len(parts) >= 3 else None


def age_factor(built, rate=0.004):
    return max(0.6, 1 - rate * (2026 - int(built)))


# ---------- offline solvers ----------
def solve_oracle(item, key):
    return {"estimate_usd": key["truth_value"], "p10_usd": key["truth_value"], "p90_usd": key["truth_value"],
            "jurisdiction": key["jurisdiction"], "excluded_comps": key["excluded"], "flags": key["traps"],
            "rationale": "oracle"}


def solve_naive(item, key=None):
    subj, comps = parse_packet(item["prompt"])
    ppsf = statistics.median(to_num(c["price"]) / to_num(c["sqft"]) for c in comps if to_num(c["sqft"]) > 0)
    est = ppsf * to_num(subj["sqft"])
    mkt = mailing_market(subj["mailing address"])  # trusts the mailing address
    state = MARKETS[mkt]["state"] if mkt else "IN"
    county = subj["situs county"] if "blank" not in subj["situs county"] else (MARKETS[mkt]["county"] if mkt else "")
    return {"estimate_usd": round(est), "p10_usd": round(est * 0.9), "p90_usd": round(est * 1.1),
            "jurisdiction": {"state": state, "county": county}, "excluded_comps": [], "flags": [],
            "rationale": "face-value median $/sqft"}


def solve_rules(item, key=None):
    subj, comps = parse_packet(item["prompt"])
    flags, excluded = set(), set()
    subj_mkt = parcel_market(subj["parcel"])  # parcel number is the authoritative jurisdiction signal
    mail_mkt = mailing_market(subj["mailing address"])
    if subj_mkt and mail_mkt and subj_mkt != mail_mkt:
        flags.add("jurisdiction_mismatch")

    seen = {}
    sale_groups = {}
    for c in comps:
        sale_groups.setdefault((c["sale_id"], c["price"]), []).append(c["id"])
    for c in comps:
        if c["src"].startswith("SDF_RAW"):
            c["_price"] = int(re.sub(r"\D", "", c["price"])) / 100
            flags.add("price_scale")
        else:
            c["_price"] = to_num(c["price"])
        sold = c["sold"]
        if "/" in sold:
            mm, dd, yy = sold.split("/")
            sold = f"{yy}-{mm}-{dd}"
        dkey = (re.sub(r"\D", "", c["parcel"]), round(c["_price"]), sold)
        if dkey in seen:
            excluded.add(c["id"])
            flags.add("duplicate_record")
            continue
        seen[dkey] = c["id"]
        if int(c.get("parcels_in_sale", 1)) > 1 or len(sale_groups[(c["sale_id"], c["price"])]) > 1:
            excluded.add(c["id"])
            flags.add("multi_parcel_sale")
        elif c["deed"] in ("QUITCLAIM", "QC") or c["grantor"].split(",")[0] == c["grantee"].split(",")[0]:
            excluded.add(c["id"])
            flags.add("non_arms_length")
        elif subj_mkt and parcel_market(c["parcel"]) != subj_mkt:
            excluded.add(c["id"])
            flags.add("cross_jurisdiction_comp")

    live = [c for c in comps if c["id"] not in excluded and to_num(c["sqft"]) > 0]
    adj = {c["id"]: c["_price"] / (to_num(c["sqft"]) * age_factor(c["built"])) for c in live}
    med = statistics.median(adj.values())
    for cid, v in adj.items():
        if v > 3 * med or v < med / 3:
            excluded.add(cid)
            flags.add("outlier")
    vals = [v for cid, v in adj.items() if cid not in excluded]
    base = statistics.median(vals)
    est = base * to_num(subj["sqft"]) * age_factor(subj["built"])
    spread = (statistics.pstdev(vals) / statistics.mean(vals)) if len(vals) > 1 else 0.08
    half = max(0.05, 1.3 * spread)
    m = MARKETS[subj_mkt] if subj_mkt else {"state": "IN", "county": ""}
    return {"estimate_usd": round(est), "p10_usd": round(est * (1 - half)), "p90_usd": round(est * (1 + half)),
            "jurisdiction": {"state": m["state"], "county": m["county"]},
            "excluded_comps": sorted(excluded), "flags": sorted(flags),
            "rationale": "decoded layouts, deduped, filtered invalid sales, age-adjusted median $/sqft"}


# ---------- live model adapters ----------
def _post(url, headers, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _env(name):
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"Missing environment variable {name}. Export it first, e.g.: export {name}=...")
    return v


def call_anthropic(model, prompt):
    data = _post("https://api.anthropic.com/v1/messages",
                 {"x-api-key": _env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01",
                  "content-type": "application/json"},
                 {"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]})
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def call_openai(model, prompt):
    data = _post("https://api.openai.com/v1/chat/completions",
                 {"Authorization": f"Bearer {_env('OPENAI_API_KEY')}", "Content-Type": "application/json"},
                 {"model": model, "messages": [{"role": "user", "content": prompt}]})
    return data["choices"][0]["message"]["content"]


def call_gemini(model, prompt):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
           f"?key={_env('GEMINI_API_KEY')}")
    data = _post(url, {"Content-Type": "application/json"}, {"contents": [{"parts": [{"text": prompt}]}]})
    return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])


PROVIDERS = {"anthropic": call_anthropic, "openai": call_openai, "gemini": call_gemini}
OFFLINE = {"oracle": solve_oracle, "naive": solve_naive, "rules": solve_rules}


def call_with_retry(fn, model, prompt, tries=4):
    for attempt in range(tries):
        try:
            return fn(model, prompt)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:300]
            if e.code in (429, 500, 502, 503, 529) and attempt < tries - 1:
                time.sleep(2 ** attempt * 5)
                continue
            return f"__ERROR__ HTTP {e.code}: {body}"
        except Exception as e:  # network hiccup
            if attempt < tries - 1:
                time.sleep(2 ** attempt * 5)
                continue
            return f"__ERROR__ {type(e).__name__}: {e}"


def get_solver(spec):
    """Returns (label, fn(item, key) -> raw_response_text)."""
    if spec in OFFLINE:
        fn = OFFLINE[spec]
        return f"baseline:{spec}", lambda item, key: json.dumps(fn(item, key))
    provider, _, model = spec.partition(":")
    if provider not in PROVIDERS or not model:
        raise SystemExit(f"Unknown solver '{spec}'. Use oracle | naive | rules | anthropic:<model> | "
                         f"openai:<model> | gemini:<model>")
    fn = PROVIDERS[provider]
    return spec, lambda item, key: call_with_retry(fn, model, item["prompt"])
