# Changelog

## 1.1.1 — 2026-09-22
- FIX: clean comparable sales no longer share any name token between grantor and grantee.
  v1.1.0 produced coincidental first-name matches on ~9% of clean comps (32/329 public_hard,
  92/1,103 holdout_hard), penalizing models that cautiously flagged them as related-party.
  Found by pilot run 001 (see pilot/ANALYSIS.md). Measured impact on that run: 82.9 → 87.4.
- All splits regenerated; holdouts re-committed; baselines re-run; full ledger re-verified
  (1,574 receipts, 1,560 re-scored, 0 mismatches).
- Hard-tier baselines: rules 94.5, naive 45.7.
- Added START-HERE.pdf, docs/REPORT-001.pdf, pilot/, tools/live-runner/.

## 1.1.0
- Hard tier (no hints), auto loop, model discovery, commit-reveal holdouts, 3-page leaderboard.
