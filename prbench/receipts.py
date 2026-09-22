"""Parcel Reality Bench — hash-chained receipts.

Every scored answer gets a receipt: sha256(prompt), sha256(response), score,
and the hash of the previous receipt. Editing any past result breaks the chain.
`verify` recomputes the chain AND re-scores every stored response against the
key, so a published leaderboard is independently reproducible.
"""
import hashlib
import json
import time
from pathlib import Path

GENESIS = "0" * 64


def sha(text):
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.head, self.seq = GENESIS, 0
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.head, self.seq = r["hash"], r["seq"]

    def append(self, body):
        rec = {"seq": self.seq + 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "prev": self.head, **body}
        rec["hash"] = sha(canon(rec))
        with open(self.path, "a") as f:
            f.write(canon(rec) + "\n")
        self.head, self.seq = rec["hash"], rec["seq"]
        return rec


def verify_chain(path):
    prev, n, problems = GENESIS, 0, []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        n += 1
        claimed = r.pop("hash")
        if r["prev"] != prev:
            problems.append(f"seq {r['seq']}: prev-link broken")
        if sha(canon(r)) != claimed:
            problems.append(f"seq {r['seq']}: content hash mismatch (record edited)")
        if r["seq"] != n:
            problems.append(f"seq {r['seq']}: sequence gap")
        prev = claimed
    return n, prev, problems


def commit_split(split_dir, salt):
    """Commit-reveal: publish this digest now, reveal key + salt later."""
    d = Path(split_dir)
    items, key = (d / "items.jsonl").read_bytes(), (d / "key.jsonl").read_bytes()
    return {"split": d.name, "items_sha256": sha(items),
            "key_commitment": sha(salt.encode() + b"|" + key),
            "scheme": "sha256(salt || '|' || key.jsonl)"}
