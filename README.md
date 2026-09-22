> **Reading this in TextEdit?** Open **START-HERE.pdf** instead. This file is Markdown and renders properly on GitHub.
> Full write-up, results, and fixes: **docs/REPORT-001.pdf**. Changes: **CHANGELOG.md**.

# Parcel Reality Bench (prbench) v1.1

**Frontier models vs. as-received county records on the Indiana–Michigan line.**
Autonomous: it detects new model releases daily, benchmarks them, verifies every score, and republishes the leaderboard. It then drafts the announcement for you to review.

Zero dependencies. Python 3 standard library only.

---

## 1. What it measures

Every item is a valuation packet: a subject parcel plus comparable sales from mixed county extracts, with labeled traps planted in the records.

| Trap | Standard tier | Hard tier |
|---|---|---|
| `price_scale` | `SDF_RAW;layout=N(12,2)`, and the layout is stated | `SDF_RAW` only; the model must know the state disclosure layout |
| `non_arms_length` | QUITCLAIM deed with a family surname | Deed code `QC` **or** a `WD` warranty deed where only the surname and a ~50% price give it away |
| `multi_parcel_sale` | `parcels_in_sale=3` is written out | No field at all. One sale appears as **three rows**, each carrying the full price, which is the real SDF pattern |
| `outlier` | 10x / 100x / 1000x keying error | 10x only, so it's plausible-looking |
| `duplicate_record` | Second source, US date format | Also an **undashed parcel number**, so a string match fails |
| `cross_jurisdiction_comp` | Comp across the state line | Same |
| `jurisdiction_mismatch` | Mailing address in the other state, situs county blank | Same, and no glossary |

**Scoring:**
- Composite = 30% valuation + 20% calibration (80% Winkler) + 25% exclusion F1 + 15% flag F1 + 10% jurisdiction.
- **Failure map:** the handled rate for each trap.
- **Provenance:** every answer is a hash-chained receipt, and both holdout keys are committed before any run.

**Baselines (demo seed):**

| Solver | Standard | Hard |
|---|---|---|
| rules (deterministic pipeline) | 94.3 | 94.5 |
| naive (face value) | 57.9 | 47.6 |

## 2. Commands

**Offline, no API key needed:**

```bash
python3 -m prbench generate          # 4 splits: public, holdout, public_hard, holdout_hard
python3 -m prbench commit --salt "…"  # commit both holdouts before any model runs
python3 -m prbench run --solver rules --split public_hard
python3 -m prbench verify             # recompute hash chain + re-score every stored response
```

**Needs API keys:**

```bash
python3 -m prbench auto --dry-run     # detect new models only
python3 -m prbench auto               # full loop: discover, run, verify, build site/, write drafts/
```

## 3. Local setup on the M1

### 3.1 Unzip and enter the folder

```bash
cd ~/Downloads && unzip prbench.zip -d ~/neuruh && cd ~/neuruh/prbench
```

- **Where it lives:** Finder → Home → neuruh → prbench.
- **Every command below is run from this folder.** `pwd` should end in `/neuruh/prbench`.

### 3.2 Generate YOUR data and commit to it

The zip ships a demo dataset. Replace it with your own:

```bash
rm -rf data results receipts drafts site
python3 -m prbench generate
python3 -m prbench commit --salt "REPLACE-WITH-A-LONG-RANDOM-SECRET"
```

- **The salt:** replace `REPLACE-WITH-A-LONG-RANDOM-SECRET` with any long random string. Store it in your password manager. You need it later to reveal the holdout.
- **Output:** two `key_commitment` hashes. Save them. They go in the launch post as proof you did not move the goalposts.

### 3.3 Put your API keys in the terminal session

Replace each placeholder after `=` with your real key:

```bash
export ANTHROPIC_API_KEY="paste-key-from-console.anthropic.com"
export OPENAI_API_KEY="paste-key-from-platform.openai.com"
export GEMINI_API_KEY="paste-key-from-aistudio.google.com"
```

These last until you close the Terminal window. Any provider without a key is skipped.

### 3.4 Bootstrap, then run

```bash
python3 -m prbench auto --bootstrap
python3 -m prbench auto
open site/index.html
```

- **`--bootstrap`:** marks every model the providers currently list as "seen," so the loop doesn't burn money benchmarking 40 legacy models. Only models in `pinned_models` stay queued.
- **`pinned_models`** lives in `bench.config.json`. It is preloaded with Opus 5, Sonnet 5, and Haiku 4.5. Add the current OpenAI and Gemini flagships as `openai:MODEL_ID` and `gemini:MODEL_ID`. Take the exact IDs from each provider's model docs page.
- **`auto`:** benchmarks the queue on all 4 splits, verifies, builds `site/`, and writes `drafts/<date>-<model>.md` plus `drafts/saturation.md`.

## 4. Put it on autopilot: GitHub Actions + Cloudflare Pages

The workflow at `.github/workflows/bench.yml` runs daily. After setup, a lab ships a model and your leaderboard has its failure map within 24 hours. The draft post waits for you in `drafts/`.

### 4.1 Install the GitHub CLI and log in

```bash
brew install gh
gh auth login
```

- When prompted, choose: GitHub.com → HTTPS → Login with a web browser.

### 4.2 Create a PRIVATE repo and push

```bash
cd ~/neuruh/prbench
git init && git add . && git commit -m "prbench v1.1"
gh repo create prbench --private --source=. --push
```

- **Why private:** the runner needs the holdout keys. The public only ever sees the deployed site.
- **The keys never reach git:** `.gitignore` blocks both holdout `key.jsonl` files.

### 4.3 Store the secrets

Each `gh secret set` command prompts you to paste the value:

```bash
gh secret set ANTHROPIC_API_KEY
gh secret set OPENAI_API_KEY
gh secret set GEMINI_API_KEY
tar czf - data/holdout/key.jsonl data/holdout_hard/key.jsonl | base64 | gh secret set HOLDOUT_KEYS_B64
gh secret set CLOUDFLARE_ACCOUNT_ID
gh secret set CLOUDFLARE_API_TOKEN
```

- **`HOLDOUT_KEYS_B64`:** the line above compresses both keys to about 12 KB and uploads them encrypted. No paste needed.
- **`CLOUDFLARE_ACCOUNT_ID`:** Cloudflare dashboard → any zone → right sidebar → "Account ID."
- **`CLOUDFLARE_API_TOKEN`:** Cloudflare → My Profile → API Tokens → Create Token → Custom token. Set the permission to Account → Cloudflare Pages → Edit.

### 4.4 Create the Pages project and custom domain

**Create the project once:**
1. Cloudflare → Workers & Pages → Create → Pages → Upload assets.
2. Name it `prbench`.
3. Drag in the `site` folder.

**Add the domain:**
1. Project → Custom domains → add `bench.neuruh.com`.
2. neuruh.com is already on Cloudflare, so DNS is automatic.

### 4.5 First cloud run

```bash
gh workflow run bench-auto
gh run watch
```

- **Expected:** the run finishes with `[verify] PASS` and a deploy URL.
- **From then on:** it runs daily at 09:17 Eastern. Results, receipts, and drafts are committed back to the repo, so the history is a public-auditable chain.

## 5. The recursive loop

`drafts/saturation.md` is rewritten on every run. It tracks how every real model does on each trap:

- **SATURATED:** every model handles the trap ≥95%. That trap is due to be hardened in the next generator version.
- **Bench saturating:** the best model's composite reaches 95%. Time to ship a new tier.

The benchmark monitors its own obsolescence, so it stays hard enough to matter.

## 6. File map

```
prbench/generate.py      item generator, 7 traps x 2 difficulty tiers, deterministic per seed
prbench/score.py         scoring + per-trap failure map
prbench/solvers.py       oracle / naive / rules baselines + Anthropic, OpenAI, Gemini adapters
prbench/discover.py      new-model detection against provider model-list endpoints
prbench/receipts.py      hash-chained ledger, verify, commit-reveal
prbench/leaderboard.py   multi-tier static site (Neuruh v1 design law)
bench.config.json        providers, filters, pinned models, splits, thresholds (config, not code)
.github/workflows/bench.yml   daily autonomous run
```
