# Pilot run 001 — 2026-09-22

- Solver: Claude via claude.ai, Default tier (not a pinned API model ID)
- Split: public_hard, generator v1.1.0, items_sha256 a51b4158b0ca6ab9…
- Items: 9 (pilot; not publishable as a score)
- Receipt chain: verified in Python, head c951d4161a5fc77c…, 0 re-score mismatches

| Metric | Value |
|---|---|
| Composite | 82.9 |
| Composite with generator-bug errors removed | 87.4 |
| Rules pipeline (v1.1.1 hard) | 94.5 |
| Face value (v1.1.1 hard) | 45.7 |

## Misses
- PRX-0002 — Berrien County MI property placed in LaPorte County IN; kept a cross-border comp. Real miss.
- PRX-0005 — excluded clean comp C06 (ROBERT → ROBERT). Generator bug.
- PRX-0006 — excluded clean comp C02 (EMILY → EMILY). Generator bug.
- All items — 80% ranges always covered truth but were wide (calibration 72.8). Real pattern.

## Bug and fix
v1.1.0 drew grantor/grantee first names independently from a 10-name pool: ~9% of clean comps
shared a first name, which a careful reader can fairly read as related-party on the hard tier.
v1.1.1 guarantees clean comps share no name token. See CHANGELOG.md.

Reproduce the exact v1.1.0 dataset: check out the v1.1.0 generator and run `python3 -m prbench generate`;
the public_hard items_sha256 must equal a51b4158b0ca6ab9….
