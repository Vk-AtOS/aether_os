# _legacy — Archived Modules

These files are from an earlier prototype (the `aether-one` mono-repo) and are **NOT used** in the production gateway or any active code path.

They are retained here for reference during acquisition due diligence only.

## Files

| File | Original purpose | Why superseded |
|------|-----------------|----------------|
| `identity.py` | Sync SQLAlchemy auth with `.aether-one/identity.db` | Replaced by `gateway/auth.py` + async ORM |
| `zero_trust.py` | ZT execution token check (legacy) | Wired into main gateway via `AETHER_ONE_ZT_SECRET` env var directly |
| `engine.py` | Legacy identity engine | Superseded by `core/identity/__init__.py` stubs |
| `licensing/licensing.py` | HMAC license token for `.aether-one` | Replaced by plan-gated billing in `core/billing.py` |

**None of these files are imported by the main application.** Safe to delete post-acquisition once confirmed.
