"""Parcel Reality Bench — new-model discovery.

Polls each provider's model-list endpoint, filters with the regexes in
bench.config.json, and diffs against receipts/models_seen.json. Anything new
(or pinned and not yet benchmarked) is queued for a run.
"""
import json
import os
import re
import time
import urllib.request
from pathlib import Path


def _get(url, headers):
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def list_anthropic():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    data = _get("https://api.anthropic.com/v1/models?limit=1000",
                {"x-api-key": key, "anthropic-version": "2023-06-01"})
    return [m["id"] for m in data.get("data", [])]


def list_openai():
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    data = _get("https://api.openai.com/v1/models", {"Authorization": f"Bearer {key}"})
    return [m["id"] for m in data.get("data", [])]


def list_gemini():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None
    data = _get(f"https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000&key={key}", {})
    return [m["name"].split("/", 1)[-1] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])]


LISTERS = {"anthropic": list_anthropic, "openai": list_openai, "gemini": list_gemini}


def discover(config, state_path):
    """Returns (queue, state, log). queue = ['provider:model', ...] not yet benchmarked."""
    state_path = Path(state_path)
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    log, now = [], time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for provider, cfg in config["providers"].items():
        if not cfg.get("enabled", True):
            continue
        try:
            ids = LISTERS[provider]()
        except Exception as e:  # provider outage never kills the whole run
            log.append(f"{provider}: list failed ({type(e).__name__}: {e})")
            continue
        if ids is None:
            log.append(f"{provider}: skipped (no API key in environment)")
            continue
        inc = [re.compile(p) for p in cfg.get("include", [".*"])]
        exc = [re.compile(p) for p in cfg.get("exclude", [])]
        kept = [m for m in ids if any(p.search(m) for p in inc) and not any(p.search(m) for p in exc)]
        fresh = 0
        for m in kept:
            spec = f"{provider}:{m}"
            if spec not in state:
                state[spec] = {"first_seen": now, "benchmarked": False}
                fresh += 1
        log.append(f"{provider}: {len(ids)} listed, {len(kept)} match filters, {fresh} new")
    for spec in config.get("pinned_models", []):
        state.setdefault(spec, {"first_seen": now, "benchmarked": False, "pinned": True})
    queue = [s for s, v in sorted(state.items(), key=lambda kv: kv[1]["first_seen"], reverse=True)
             if not v["benchmarked"]]
    return queue[: config.get("max_new_models_per_run", 4)], state, log


def mark_benchmarked(state, spec, state_path, composite_by_split):
    state[spec].update(benchmarked=True, benchmarked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       composite=composite_by_split)
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(state, indent=2))


def save_state(state, state_path):
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps(state, indent=2))
