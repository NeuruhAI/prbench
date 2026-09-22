"""Parcel Reality Bench — item generator.

Builds county-record valuation packets with planted, labeled data traps drawn
from real Michiana (IN/MI border) public-records failure modes. Deterministic
per seed, so a split can be regenerated and its hash re-verified.
"""
import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

GENERATOR_VERSION = "1.1.1"
VALUATION_DATE = "2026-07-01"

MARKETS = {
    "IN-LaPorte":    {"state": "IN", "county": "LaPorte",    "code": "46", "ppsf": 142, "acre": 8500},
    "IN-St. Joseph": {"state": "IN", "county": "St. Joseph", "code": "71", "ppsf": 128, "acre": 9500},
    "IN-Porter":     {"state": "IN", "county": "Porter",     "code": "64", "ppsf": 171, "acre": 11000},
    "MI-Berrien":    {"state": "MI", "county": "Berrien",    "code": "11", "ppsf": 163, "acre": 12000},
    "MI-Cass":       {"state": "MI", "county": "Cass",       "code": "14", "ppsf": 131, "acre": 7000},
}
NEIGHBOR = {
    "IN-LaPorte": "MI-Berrien", "IN-St. Joseph": "MI-Cass", "IN-Porter": "MI-Berrien",
    "MI-Berrien": "IN-LaPorte", "MI-Cass": "IN-St. Joseph",
}
TOWNS = {
    "IN-LaPorte": ["Michigan City", "La Porte", "Michiana Shores", "Westville", "Long Beach"],
    "IN-St. Joseph": ["South Bend", "Mishawaka", "New Carlisle", "Granger", "Walkerton"],
    "IN-Porter": ["Valparaiso", "Chesterton", "Portage", "Kouts"],
    "MI-Berrien": ["Niles", "New Buffalo", "Three Oaks", "Michiana", "Benton Harbor", "St. Joseph"],
    "MI-Cass": ["Edwardsburg", "Cassopolis", "Dowagiac", "Vandalia"],
}
STREETS = ["Oak St", "Maple Ave", "Lincoln Way", "Red Arrow Hwy", "County Rd 400 N",
           "Lake Shore Dr", "Elm St", "Cedar Ln", "Timm Rd", "Wilson Rd", "Pokagon Rd", "US 12"]
SURNAMES = ["MILLER", "KOWALSKI", "NOWAK", "JOHNSON", "HICKS", "BRANDT", "OKAFOR", "REYES",
            "SCHMIDT", "WALSH", "PATEL", "DUBOIS", "LINDQVIST", "HARTMAN", "CHEN", "MORALES"]
FIRST = ["JOHN", "EMILY", "MARCUS", "DIANE", "ROBERT", "LUCIA", "PAUL", "TANYA", "OMAR", "GRACE"]

TRAPS = ["price_scale", "non_arms_length", "multi_parcel_sale", "outlier",
         "duplicate_record", "cross_jurisdiction_comp", "jurisdiction_mismatch"]
EXCLUSION_TRAPS = ["non_arms_length", "multi_parcel_sale", "outlier",
                   "duplicate_record", "cross_jurisdiction_comp"]


def true_value(m, sqft, acres, built):
    age_factor = max(0.62, 1 - 0.0045 * (2026 - built))
    return int(round(m["ppsf"] * sqft * age_factor + m["acre"] * acres, -2))


def round_to(x, step):
    return int(round(x / step) * step)


def parcel_id(rng, mkt):
    m = MARKETS[mkt]
    if m["state"] == "IN":  # Indiana 18-digit state parcel number, county code first
        return (f'{m["code"]}-{rng.randint(1, 20):02d}-{rng.randint(1, 36):02d}-'
                f'{rng.choice([100, 200, 300, 400])}-{rng.randint(1, 99):03d}.000-{rng.randint(1, 30):03d}')
    return (f'{m["code"]}-{rng.randint(1, 30):02d}-{rng.randint(1, 9999):04d}-'
            f'{rng.randint(1, 9999):04d}-{rng.randint(0, 99):02d}-{rng.randint(0, 9)}')


def person(rng, surname=None, first=None):
    return f"{surname or rng.choice(SURNAMES)}, {first or rng.choice(FIRST)}"


def make_house(rng, base=None):
    if base is None:
        return {"sqft": rng.randint(1100, 2600), "built": rng.randint(1950, 2015),
                "acres": round(rng.uniform(0.15, 1.2), 2)}
    return {"sqft": int(base["sqft"] * rng.uniform(0.82, 1.18)),
            "built": min(2024, max(1930, base["built"] + rng.randint(-12, 12))),
            "acres": round(max(0.08, base["acres"] * rng.uniform(0.7, 1.3)), 2)}


def sale_date(rng):
    return date(2025, 7, 1) + timedelta(days=rng.randint(0, 360))


def new_comp(rng, mkt, house, price):
    m = MARKETS[mkt]
    # v1.1.1: clean sales share NO name token between grantor and grantee. v1.1.0 drew first
    # names independently, so ~9% of clean comps had coincidental matches (e.g. ROBERT -> ROBERT)
    # that a careful model could fairly read as related-party. Found by the first claude.ai run.
    s1, s2 = rng.sample(SURNAMES, 2)
    f1, f2 = rng.sample(FIRST, 2)
    return {
        "uid": rng.getrandbits(48), "mkt": mkt, "src": rng.choice(["COUNTY_CSV", "ASSESSOR_WEB", "MLS_EXPORT"]),
        "parcel": parcel_id(rng, mkt), "town": rng.choice(TOWNS[mkt]), "state": m["state"],
        "sale_id": f"S-{rng.randint(10000, 99999)}", "parcels_in_sale": 1, "sold": sale_date(rng),
        "date_fmt": "iso", "deed": rng.choice(["WARRANTY", "WARRANTY", "WARRANTY", "SPECIAL WARRANTY"]),
        "grantor": person(rng, s1, f1), "grantee": person(rng, s2, f2), "price": price, "price_fmt": "usd",
        **house,
    }


DEED_CODES = {"WARRANTY": "WD", "SPECIAL WARRANTY": "SW", "QUITCLAIM": "QC"}


def render_comp(c, hard=False):
    if c["price_fmt"] == "sdf":
        price = f"{int(round(c['price'] * 100)):014d}"
        src = "SDF_RAW" if hard else "SDF_RAW;layout=N(12,2)"  # hard: layout must be known, not told
    elif c["price_fmt"] == "plain":
        price, src = f"{c['price']:.2f}", c["src"]
    else:
        price, src = f"${c['price']:,.0f}", c["src"]
    sold = c["sold"].strftime("%m/%d/%Y") if c["date_fmt"] == "us" else c["sold"].isoformat()
    parcel = c["parcel"]
    if hard and c.get("undashed"):
        parcel = "".join(ch for ch in parcel if ch.isdigit())  # same parcel, different extract format
    fields = [f"parcel={parcel}", f"town={c['town']}, {c['state']}", f"sale_id={c['sale_id']}"]
    if not hard:
        fields.append(f"parcels_in_sale={c['parcels_in_sale']}")
    fields += [f"sold={sold}", f"deed={DEED_CODES[c['deed']] if hard else c['deed']}",
               f"grantor={c['grantor']}", f"grantee={c['grantee']}", f"sqft={c['sqft']:,}",
               f"built={c['built'] if c['sqft'] else '-'}", f"acres={c['acres']:.2f}", f"price={price}"]
    return f"  {c['id']} [src={src}] " + " | ".join(fields)


FLAG_NAMES = ("price_scale, non_arms_length, multi_parcel_sale, outlier, duplicate_record, "
              "cross_jurisdiction_comp, jurisdiction_mismatch")
SCHEMA = """Return ONLY a JSON object, no prose, no code fences:
{"estimate_usd": <number>, "p10_usd": <number>, "p90_usd": <number>,
 "jurisdiction": {"state": "IN" or "MI", "county": "<county name>"},
 "excluded_comps": ["C..", ...],
 "flags": [zero or more flag names],
 "rationale": "<one sentence>"}
p10/p90 are your 10th and 90th percentile bounds (an 80% interval)."""

INSTRUCTIONS = """TASK
Estimate the market value of the SUBJECT as of the valuation date.
Rules:
- Valid comparables are arm's-length, single-parcel sales located in the subject's own county market.
- Records are as-received from mixed extracts and may contain layout, keying, and duplication errors.
  Decode what can be decoded. Exclude what is invalid.
- Determine the subject's jurisdiction (state + county) from the most authoritative evidence in the record.
Flag glossary: price_scale (price stored in an implied-decimal layout), non_arms_length (related-party or
non-market transfer), multi_parcel_sale (one price covers several parcels), outlier (keying error),
duplicate_record (same sale listed twice), cross_jurisdiction_comp (comp outside subject's county market),
jurisdiction_mismatch (subject's mailing address points to a different jurisdiction than the parcel).
""" + SCHEMA

INSTRUCTIONS_HARD = """TASK
Estimate the market value of the SUBJECT as of the valuation date, using only valid comparable sales.
Records are as-received from state disclosure files, assessor exports, and MLS feeds. SDF_RAW rows use
the state sales-disclosure file layout. Determine the subject's jurisdiction (state + county).
Allowed flag names: """ + FLAG_NAMES + "\n" + SCHEMA


def build_item(rng, item_id, hard=False):
    mkt = rng.choice(list(MARKETS))
    m = MARKETS[mkt]
    subj = make_house(rng)
    truth = true_value(m, **subj)
    traps = rng.sample(TRAPS, rng.choice([0, 1, 2, 2, 3, 3, 4] if not hard else [1, 2, 3, 3, 4, 4, 5]))

    comps = [new_comp(rng, mkt, h, round_to(true_value(m, **h) * rng.uniform(0.94, 1.06), 500))
             for h in (make_house(rng, subj) for _ in range(rng.randint(5, 6)))]
    clean = list(comps)
    trap_uid, dup_src_uid = {}, None

    if "price_scale" in traps:
        c = rng.choice(clean)
        c["price_fmt"] = "sdf"
        trap_uid["price_scale"] = [c["uid"]]
    if "duplicate_record" in traps:
        src = rng.choice([x for x in clean if x["price_fmt"] != "sdf"])
        d = dict(src, uid=rng.getrandbits(48), price_fmt="plain", date_fmt="us", undashed=hard,
                 src=rng.choice([s for s in ["COUNTY_CSV", "ASSESSOR_WEB", "MLS_EXPORT"] if s != src["src"]]),
                 sale_id=f"DOC-{rng.randint(100000, 999999)}")
        comps.append(d)
        trap_uid["duplicate_record"], dup_src_uid = [d["uid"]], src["uid"]
    if "non_arms_length" in traps:
        h = make_house(rng, subj)
        c = new_comp(rng, mkt, h, round_to(true_value(m, **h) * rng.uniform(0.35, 0.6), 500))
        sur = rng.choice(SURNAMES)
        deed = "QUITCLAIM" if (not hard or rng.random() < 0.5) else "WARRANTY"  # hard: warranty deed, family names
        c.update(deed=deed, grantor=person(rng, sur), grantee=person(rng, sur))
        comps.append(c)
        trap_uid["non_arms_length"] = [c["uid"]]
    if "multi_parcel_sale" in traps:
        h = make_house(rng, subj)
        total = round_to(true_value(m, **h) * rng.uniform(1.25, 1.6), 500)  # house + 2 adjoining lots
        c = new_comp(rng, mkt, h, total)
        c["parcels_in_sale"] = 3
        group = [c]
        if hard:  # real SDF pattern: every parcel in the sale is its own row carrying the full price
            for _ in range(2):
                lot = dict(c, uid=rng.getrandbits(48), parcel=parcel_id(rng, mkt), sqft=0,
                           acres=round(rng.uniform(0.1, 0.4), 2))
                group.append(lot)
        else:
            c["price"] = round_to(true_value(m, **h) * rng.uniform(2.6, 3.3), 500)
        comps.extend(group)
        trap_uid["multi_parcel_sale"] = [g["uid"] for g in group]
    if "outlier" in traps:
        h = make_house(rng, subj)
        mult = 10 if hard else rng.choice([10, 100, 1000])
        c = new_comp(rng, mkt, h, round_to(true_value(m, **h) * rng.uniform(0.96, 1.04), 500) * mult)
        comps.append(c)
        trap_uid["outlier"] = [c["uid"]]
    if "cross_jurisdiction_comp" in traps:
        nm = NEIGHBOR[mkt]
        h = make_house(rng, subj)
        c = new_comp(rng, nm, h, round_to(true_value(MARKETS[nm], **h) * rng.uniform(0.94, 1.06), 500))
        comps.append(c)
        trap_uid["cross_jurisdiction_comp"] = [c["uid"]]

    rng.shuffle(comps)
    for i, c in enumerate(comps, 1):
        c["id"] = f"C{i:02d}"
    by_uid = {c["uid"]: c["id"] for c in comps}
    trap_comps = {t: sorted(by_uid[u] for u in uids) for t, uids in trap_uid.items()}

    dup_pairs = []
    if dup_src_uid is not None:
        a, b = sorted([by_uid[dup_src_uid], trap_comps["duplicate_record"][0]])
        dup_pairs = [[a, b]]
        trap_comps["duplicate_record"] = [b]  # gold excludes the later-listed copy

    excluded = sorted({cid for t in EXCLUSION_TRAPS for cid in trap_comps.get(t, [])})

    mismatch = "jurisdiction_mismatch" in traps
    home_mkt = NEIGHBOR[mkt] if mismatch else mkt
    blank_county = mismatch or rng.random() < 0.3
    mail_town = rng.choice(TOWNS[home_mkt])
    subject_lines = [
        "SUBJECT",
        f"  parcel: {parcel_id(rng, mkt)}",
        f"  situs county: {'[blank in extract]' if blank_county else m['county']}",
        f"  mailing address: {rng.randint(100, 9999)} {rng.choice(STREETS)}, {mail_town}, {MARKETS[home_mkt]['state']}",
        f"  sqft: {subj['sqft']:,}",
        f"  built: {subj['built']}",
        f"  acres: {subj['acres']:.2f}",
    ]
    prompt = "\n".join([
        f"PARCEL VALUATION PACKET {item_id}",
        f"Valuation date: {VALUATION_DATE}",
        "",
        *subject_lines,
        "",
        "COMPARABLE SALE RECORDS",
        *[render_comp(c, hard) for c in comps],
        "",
        INSTRUCTIONS_HARD if hard else INSTRUCTIONS,
    ])
    key = {
        "id": item_id, "truth_value": truth, "difficulty": "hard" if hard else "standard",
        "jurisdiction": {"state": m["state"], "county": m["county"]},
        "excluded": excluded, "dup_pairs": dup_pairs, "traps": sorted(traps),
        "trap_comps": trap_comps,
    }
    return {"id": item_id, "prompt": prompt}, key


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def generate_split(out_dir, split, n, seed):
    hard = split.endswith("_hard")
    rng = random.Random(f"prb-{split}-{seed}")
    d = Path(out_dir) / split
    d.mkdir(parents=True, exist_ok=True)
    prefix = {"public": "PRB", "holdout": "PRH", "public_hard": "PRX", "holdout_hard": "PRZ"}[split]
    items, keys = zip(*(build_item(rng, f"{prefix}-{i:04d}", hard) for i in range(1, n + 1)))
    with open(d / "items.jsonl", "w") as f:
        for it in items:
            f.write(json.dumps({"split": split, **it}) + "\n")
    with open(d / "key.jsonl", "w") as f:
        for k in keys:
            f.write(json.dumps(k, sort_keys=True) + "\n")
    trap_counts = {t: sum(t in k["traps"] for k in keys) for t in TRAPS}
    meta = {"split": split, "n": n, "difficulty": "hard" if hard else "standard",
            "generator_version": GENERATOR_VERSION,
            "items_sha256": sha256_file(d / "items.jsonl"), "key_sha256": sha256_file(d / "key.jsonl"),
            "trap_counts": trap_counts}
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta
