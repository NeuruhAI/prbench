import json, os, urllib.request, urllib.error
CANDIDATES = [
    ("anthropic", "claude-opus-5"), ("anthropic", "claude-sonnet-5"), ("anthropic", "claude-haiku-4-5-20251001"),
    ("openai", "gpt-6-astra"), ("openai", "gpt-5.6-sol"),
    ("gemini", "gemini-3.8-flash"),
    ("gemini", "gemini-3.1-pro-preview"), ("gemini", "gemini-3-pro-preview"), ("gemini", "gemini-pro-latest"),
]
def post(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())
def ping(provider, model):
    p = "Reply with the single word OK."
    if provider == "anthropic":
        post("https://api.anthropic.com/v1/messages",
             {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"},
             {"model": model, "max_tokens": 20, "messages": [{"role": "user", "content": p}]})
    elif provider == "openai":
        post("https://api.openai.com/v1/chat/completions",
             {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"},
             {"model": model, "messages": [{"role": "user", "content": p}]})
    else:
        post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={os.environ['GEMINI_API_KEY']}",
             {"Content-Type": "application/json"}, {"contents": [{"parts": [{"text": p}]}]})
passed, gemini_pro_done = [], False
for provider, model in CANDIDATES:
    if provider == "gemini" and "pro" in model and gemini_pro_done:
        continue
    try:
        ping(provider, model); ok = "PASS"
        passed.append(f"{provider}:{model}")
        if provider == "gemini" and "pro" in model: gemini_pro_done = True
    except urllib.error.HTTPError as e:
        ok = f"FAIL HTTP {e.code}: " + " ".join(e.read().decode(errors='replace').split())[:140]
    except Exception as e:
        ok = f"FAIL {type(e).__name__}: {e}"
    print(f"{provider}:{model:<28} {ok}")
if not passed:
    raise SystemExit("\nNO MODELS PASSED. bench.config.json NOT changed. Send the FAIL lines above.")
cfg = json.load(open("bench.config.json"))
cfg["pinned_models"] = passed
cfg["max_new_models_per_run"] = 0
cfg["providers"]["openai"]["exclude"] = sorted(set(cfg["providers"]["openai"]["exclude"]) | {"cyber","daybreak","rosalind","live","codex","pro"})
json.dump(cfg, open("bench.config.json", "w"), indent=2)
print(f"\nWROTE bench.config.json with {len(passed)} verified models:")
for m in passed: print("  ", m)
