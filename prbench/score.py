"""Parcel Reality Bench — scoring.

Composite = 0.30 valuation + 0.20 calibration + 0.25 exclusion F1
          + 0.15 flag F1 + 0.10 jurisdiction.
Plus a per-trap 'handled' map: the failure-mode breakdown labs care about.
"""
import json
import re

from .generate import TRAPS, EXCLUSION_TRAPS

WEIGHTS = {"valuation": 0.30, "calibration": 0.20, "exclusion": 0.25, "flags": 0.15, "jurisdiction": 0.10}
COMPONENTS = list(WEIGHTS)


def extract_json(text):
    """Pull the first JSON object out of a model response. Returns dict or None."""
    if text is None:
        return None
    if isinstance(text, dict):
        return text
    text = re.sub(r"```(?:json)?", "", text)
    start, depth = text.find("{"), 0
    if start < 0:
        return None
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def num(x):
    try:
        v = float(str(x).replace(",", "").replace("$", ""))
        return v if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


def f1(pred, gold):
    pred, gold = set(pred), set(gold)
    if not pred and not gold:
        return 1.0
    tp = len(pred & gold)
    if tp == 0:
        return 0.0
    p, r = tp / len(pred), tp / len(gold)
    return 2 * p * r / (p + r)


def norm_county(s):
    s = str(s or "").lower().replace("county", "").replace("saint", "st")
    return re.sub(r"[^a-z]", "", s)  # "St. Joseph" == "Saint Joseph"; "La Porte" == "LaPorte"


def normalized_exclusions(pred, key):
    pred = {str(p).strip().upper() for p in (pred or []) if p}
    for a, b in key["dup_pairs"]:
        if a in pred and b not in pred:  # excluding either copy of a duplicate is correct
            pred.discard(a)
            pred.add(b)
    return pred


def score_item(answer, key):
    truth = key["truth_value"]
    zero = {c: 0.0 for c in COMPONENTS}
    handled = {t: False for t in key["traps"]}
    if not isinstance(answer, dict):
        return {**zero, "composite": 0.0, "parse_ok": False, "ape": None, "covered": False, "handled": handled}

    est = num(answer.get("estimate_usd"))
    ape = abs(est - truth) / truth if est is not None and est > 0 else None
    valuation = max(0.0, 1 - ape / 0.25) if ape is not None else 0.0

    lo, hi = num(answer.get("p10_usd")), num(answer.get("p90_usd"))
    calibration, covered = 0.0, False
    if lo is not None and hi is not None and 0 < lo <= hi:
        alpha = 0.2  # Winkler interval score for an 80% interval
        interval = (hi - lo) + (2 / alpha) * max(0, lo - truth) + (2 / alpha) * max(0, truth - hi)
        calibration = max(0.0, 1 - (interval / truth) / 0.6)
        covered = lo <= truth <= hi

    excl = normalized_exclusions(answer.get("excluded_comps"), key)
    exclusion = f1(excl, key["excluded"])
    flags_pred = {str(f).strip().lower() for f in (answer.get("flags") or []) if f}
    flags = f1(flags_pred & set(TRAPS), key["traps"]) if (flags_pred & set(TRAPS)) or key["traps"] else 1.0

    j = answer.get("jurisdiction") or {}
    juris_ok = (str(j.get("state", "")).strip().upper() == key["jurisdiction"]["state"]
                and norm_county(j.get("county")) == norm_county(key["jurisdiction"]["county"]))
    jurisdiction = 1.0 if juris_ok else 0.0

    for t in key["traps"]:
        if t in EXCLUSION_TRAPS:
            handled[t] = all(cid in excl for cid in key["trap_comps"][t])
        elif t == "price_scale":
            # must recognize the layout (flag) AND keep the decoded sale as a valid comp
            handled[t] = "price_scale" in flags_pred and key["trap_comps"][t][0] not in excl
        elif t == "jurisdiction_mismatch":
            handled[t] = juris_ok

    parts = {"valuation": valuation, "calibration": calibration, "exclusion": exclusion,
             "flags": flags, "jurisdiction": jurisdiction}
    composite = sum(WEIGHTS[k] * v for k, v in parts.items())
    return {**parts, "composite": composite, "parse_ok": True, "ape": ape, "covered": covered, "handled": handled}


def summarize(scored):
    n = len(scored) or 1
    out = {c: sum(s[c] for s in scored) / n for c in COMPONENTS + ["composite"]}
    out["parse_rate"] = sum(s["parse_ok"] for s in scored) / n
    out["coverage_80"] = sum(s["covered"] for s in scored) / n
    apes = sorted(s["ape"] for s in scored if s["ape"] is not None)
    out["median_ape"] = apes[len(apes) // 2] if apes else None
    out["n"] = len(scored)
    traps = {}
    for t in TRAPS:
        hits = [s["handled"][t] for s in scored if t in s["handled"]]
        traps[t] = {"n": len(hits), "handled_rate": (sum(hits) / len(hits)) if hits else None}
    out["traps"] = traps
    return out
