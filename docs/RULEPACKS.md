# Rule packs (`core/rulepacks/`, KAN-243)

Three packs for generated projects: **design**, **security** and **prodready**. Each pack has two halves:

1. **Prompt rules** given to the model before it writes code: short, numbered, imperative.
2. **Deterministic checks** run on what it wrote: regex and Python `ast` only. Nothing in the scanned project
   is imported or executed, and no model or network is used.

The package does not plug into the pipeline yet. The stages call it as shown below.

```python
from aether_os.core.rulepacks import (generate_tokens, design_prompt_rules, security_prompt_rules,
                                      detect_features, scan_project, repair_prompt)

tokens = generate_tokens("booking", brand_name="Juniper Dental", moods=["calm"], primary="#2a7f8f")
open("frontend/src/index.css", "w").write(tokens.to_css())     # :root + .dark, shadcn variable names
tailwind_extend = tokens.to_tailwind()                          # theme.extend snippet (Tailwind v3)
prompt = design_prompt_rules("booking", tokens) + "\n" + security_prompt_rules(["fastapi", "react"])

report = scan_project(project_dir, public_routes=["/health", "POST /auth/login", "GET /products/*"])
report.blocking            # any high/critical finding
report.to_json()           # findings grouped by pack, counts by severity
for f in report.files():   # repair loop: at most 3 rounds, re-scan after each
    fix = repair_prompt(report.findings, f)
```

Every finding has `rule_id`, `pack`, `severity` (info/low/medium/high/critical), `file`, `line`, `message`,
`fix_hint` and the offending line as `snippet`. A project-level finding (for example "no CI workflow") has
`file == ""` and `line == 0`. When checks disagree, fewer findings win: each check is written to miss a case
rather than flag correct code, because every finding becomes an instruction to the model.

## Design tokens

`generate_tokens(site_type, brand_name, moods, primary)` is deterministic: the same inputs always give the same
output. Site types are `landing`, `saas_dashboard`, `ecommerce`, `booking`, `content`, `portfolio`,
`internal_tool` and `agent_chat`. Aliases such as `blog`, `shop` and `chat` also work.

- The colors come from brand and neutral ramps (50..950) in OKLCH. The neutrals are tinted toward the brand hue.
  The semantic tokens use the shadcn names (`--background`, `--foreground`, `--primary`,
  `--primary-foreground`, `--secondary`, `--muted`, `--muted-foreground`, `--accent`, `--destructive`,
  `--border`, `--input`, `--ring`, `--card`, `--popover`, `--chart-1..5`, `--sidebar-*`) and come in light
  and dark sets. `--success` and `--warning` are added.
- **Contrast is enforced.** Every text pair must reach 4.5:1 (WCAG AA). Every UI pair (`primary`, `ring`,
  `input` and `chart-*` against the page) must reach 3:1. A pair that falls short is moved in OKLCH lightness
  until it passes, and `tokens.adjustments` records the change. `--border` is decorative and is not held to 3:1.
  Form fields use `--input`, which is.
- Type scale ratios: 1.2 for dense apps, 1.25 for general sites and 1.333 for landing pages and portfolios. The
  body size is 14px for dashboards, 18px for content sites and 16px otherwise. On landing pages and portfolios
  the large steps use `clamp()`.
- Spacing sits on a 4px grid (keys use Tailwind units, so 1 = 4px). There are three radius sizes plus `full`,
  and three layered shadows tinted with the brand hue. Motion durations are 100, 150, 200 and 300 ms.
- Font pairs come from a curated table of Google Fonts. The table is matched on site type and mood, and the
  brand name breaks ties. Inter appears only for internal tools. The import URL loads at most 4 weights per
  family with `display=swap`.
- If no primary color is given, the hue comes from the mood words. Failing that, it is a seeded offset from
  the site-type default, kept outside the 270-320 degree violet band.

## Prompt packs

- `design_prompt_rules(site_type, tokens=None)` covers the layout pattern and section order for the site type,
  token-only colors, the 4px grid, hierarchy, the four UI states, accessibility basics, copy, mobile, images,
  a motion budget and the list of generic generated looks to avoid. Every site type stays under 1200 tokens.
- `security_prompt_rules(features)` always includes the core rules. It adds one module per feature: `fastapi`,
  `sqlalchemy`, `jwt-auth`, `file-upload`, `react`, `docker`, `llm-agent`. `detect_features(path)` picks the
  modules for an existing project. Each rule names the check id that verifies it.

## Design checks (DES)

| Id | Severity | Flags | Does not flag |
|---|---|---|---|
| DES-001 | medium | hex color in `.tsx`/`.jsx` or in a CSS file that is not the token file | `href="#id"` anchors; the token file (`--background:` present, or a `theme`/`token`/`tailwind.config` file) |
| DES-002 | low | raw Tailwind palette classes (`bg-blue-500`), one finding per file with the count | semantic classes |
| DES-003 | medium | more than 2 font families in the project (monospace not counted) | `var(--font-*)`, generic and system families |
| DES-004 | low | arbitrary spacing off the 4px grid (`p-[13px]`) | multiples of 4, 1-2px hairlines |
| DES-005 | medium | `<img>` without `alt` | `alt=""`, spread props |
| DES-006 | medium | `<button>`/`<Button>` with no text, `aria-label`, `title` or label prop | sr-only text, `{expression}` children, `components/ui/*` primitives |
| DES-007 | medium | input/textarea/select with no label, `aria-label` or matching `htmlFor` | wrapping `<label>`, `FormControl`, hidden/submit inputs, primitives |
| DES-008 | medium | `onClick` on a div/span/li/... without `role` plus a key handler | `aria-hidden` backdrops, `stopPropagation` wrappers |
| DES-009 | medium | page file (`pages/`, `routes/`, `*Page.tsx`) that fetches but lacks a loading, error or empty state (empty only when it maps over fetched data) | non-page components |
| DES-010 | low | gradient text (`bg-clip-text text-transparent` plus a gradient) | |
| DES-011 | medium | violet/indigo-to-pink gradient | other gradients |
| DES-012 | medium / low | lorem ipsum (medium); John Doe, Acme, Feature One, example.com links (low) | the same words in a `placeholder=` attribute |
| DES-013 | low | stock marketing phrases (revolutionize, seamless, unlock the power, ...) | |
| DES-014 | low | `outline-none` without a focus style on the same line | `focus-visible:ring-*` |
| DES-015 | low | more than 3 animated elements in one file; animation with no reduced-motion fallback anywhere | `animate-spin`, `animate-pulse` |
| DES-016 | medium | `<html>` without `lang`; missing viewport meta; viewport that blocks zoom | |

## Security checks (SEC)

| Id | Severity | Flags | Does not flag |
|---|---|---|---|
| SEC-001 | critical..medium | provider key formats (AWS, Stripe, Google, GitHub, Slack, OpenAI-style, Anthropic) in any file; secret-named Python variables with a literal value (high; seed dicts and call keywords medium); credentials inside a URL (medium); secrets in Dockerfile ENV/ARG | `.env.example`, tests, lock files, markdown, placeholders (`change-me`, `your-...`, `${VAR}`), values with spaces |
| SEC-002 | high | signing secret (`SECRET_KEY`, `JWT_SECRET`, ...) with any literal default, including `os.getenv(name, "x")` | `os.environ[...]`, no default |
| SEC-003 | critical | private key material in the project | certificates |
| SEC-004 | high | f-string, `+`, `%` or `.format` SQL passed to `execute`/`text()`/`exec_driver_sql`, directly or through a local variable | bound parameters, non-SQL logging f-strings |
| SEC-005 | high / medium | `eval`/`exec` on non-literals; `yaml.load` without SafeLoader; `shell=True`; `os.system` with a built command; pickle/marshal/shelve; `torch.load` without `weights_only` | `yaml.safe_load`, argument-list subprocess |
| SEC-006 | medium | `debug=True`; `DEBUG = True`; `reload=True` outside `__main__`; container CMD with `--reload` or a dev server | reload under the `__main__` guard |
| SEC-007 | high (writes) / medium (reads) | route with no auth dependency. The checker resolves `APIRouter(dependencies=)`, `include_router(..., dependencies=)` across modules, route `dependencies=`, `Depends`/`Security` params and `Annotated` aliases. A project with no auth at all gets one high finding | paths in `public_routes` (`/path`, `METHOD /path`, `/prefix/*`, matched with or without `/api[/vN]`); health and ready are always public |
| SEC-008 | medium | route with an `{...id}` path param that loads by that id (`db.get`, `filter(X.id == id)`, `filter_by`) and never references owner/tenant/current user | handlers that filter by owner or call an ownership dependency |
| SEC-009 | high | `allow_origins=["*"]` (or a `.*` regex) together with `allow_credentials=True` | wildcard without credentials |
| SEC-010 | critical / high | `jwt.decode` with verification off or an algorithm list that allows `none` or comes from the token (critical); no `algorithms=` (high) | a fixed list |
| SEC-011 | high | md5/sha*/`hashlib.new` hashing of passwords; weak passlib schemes; a plain `password` column or a `password == password` comparison when the project has no hashing library | digests of non-password data |
| SEC-012 | medium | FastAPI app with no security headers in code or nginx config | any of CSP, nosniff, frame options, HSTS or Referrer-Policy present |
| SEC-013 | medium | POST login/register/token/reset route without a limiter decorator or dependency | a global limiter (slowapi middleware, nginx `limit_req`) |
| SEC-014 | medium | auth token written to localStorage/sessionStorage | other keys |
| SEC-015 | high / medium | `dangerouslySetInnerHTML` without DOMPurify/sanitize; `eval`/`new Function` (high); `innerHTML =`/`document.write` (medium) | sanitized values |
| SEC-016 | low | `target="_blank"` without `rel` noopener/noreferrer | |
| SEC-017 | medium / low | base image `:latest` or untagged; final stage runs as root (low for nginx images) | stage aliases, digests, `*-unprivileged`, distroless nonroot |
| SEC-018 | high | `verify=False`, `ssl._create_unverified_context`, `CERT_NONE` | |
| SEC-019 | medium | `random.*` inside a function named for tokens, OTPs, secrets, resets or salts | other uses of random |
| SEC-020 | low / medium | requirements lines without `==` (low, one per file); package.json `*`/`latest` (medium) | `-r`, options, URLs |
| SEC-021 | high / medium | a committed `.env` (high if it holds secret-named values); `VITE_*SECRET*/PRIVATE/PASSWORD` names | `.env.example` / `.sample` / `.template` |
| SEC-022 | low | final Dockerfile stage without HEALTHCHECK | `HEALTHCHECK` present |

## Prod-readiness checks (PRD)

| Id | Severity | Flags |
|---|---|---|
| PRD-001 | high | backend without `GET /health` (also accepted: `/healthz`, `/livez`, `/ping`, with or without `/api`) |
| PRD-002 | medium | no `/ready` (or health) handler that touches the database |
| PRD-003 | high | SQLAlchemy in use but no Alembic env, or no revision that creates the schema |
| PRD-004 | medium | `metadata.create_all` in the production path (allowed in tests, scripts and alembic, and inside an `if` on an env, test or debug switch) |
| PRD-005 | high / medium | `DATABASE_URL` falling back to SQLite, a SQLite settings default or a literal `create_engine` URL (high); SQLAlchemy used but `DATABASE_URL` never read (medium) |
| PRD-006 | medium / high | no `.env.example`, or one that misses variables read by `os.getenv`/`os.environ`/pydantic settings/`import.meta.env`/`process.env`/compose `${VAR}` (medium); a real-looking secret in it (high) |
| PRD-007 | low | `print()` in application code; no logging configuration |
| PRD-008 | medium | `requests.*` / `urlopen` without `timeout`; httpx or aiohttp with `timeout=None` (httpx has a default) |
| PRD-009 | medium / low | backend without a Dockerfile (medium); compose service without a healthcheck (low). Migrate and seed jobs are exempt |
| PRD-010 | medium | no CI workflow (GitHub Actions, GitLab, CircleCI, Bitbucket or a Jenkinsfile) |
| PRD-011 | high / medium | `NotImplementedError` outside abstract methods and elided code such as "rest of the code" (high); `TODO`/`FIXME`/`HACK`/`XXX` comments (medium) |
| PRD-012 | medium / low | no README (medium); a README without run or deploy steps (low) |
| PRD-013 | high / medium | a demo seed function called at startup without an env flag (high); an entrypoint or CMD that runs the seed unconditionally (medium) |

## Adding a rule

Every new rule needs a positive and a near-miss negative case. Add them to the `POSITIVE`/`NEGATIVE` tables in
`tests/test_rulepacks_*.py`. The clean project in `tests/rulepacks_fixtures.py` must still produce zero findings.
Sources and licences are listed in `core/rulepacks/NOTICE.md`. Rule text is always our own wording.
