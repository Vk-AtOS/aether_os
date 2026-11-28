# Sources and licences for core/rulepacks

All code, tables and rule text in this package were written for AetherOS. No file, rule text, YAML pattern
or CSV row was copied from the projects below; they were read for ideas, and the ideas were re-stated in our
own words and re-implemented from scratch.

| Idea taken | Source | Licence | How it is used here |
|---|---|---|---|
| Plan the design system before code; list of generic "AI look" tells | anthropics/skills, frontend-design skill | own licence (all rights reserved for text) | paraphrased into `design_rules.SLOP`; no text copied |
| Site type -> pattern / palette mood / font mood reasoning; font pairing table; pre-delivery checklist | nextlevelbuilder/ui-ux-pro-max-skill | MIT | structure of `design_catalog`; our own rows and pairs |
| Semantic CSS variable names (`--background`, `--primary-foreground`, ...) and light/dark sets | shadcn-ui/ui | MIT | the variable naming contract in `design_tokens` |
| One job per step of a color scale | radix-ui/colors | MIT | ramp lightness ladder idea; our own values |
| Scales as ladders (space, radius, shadow, easing) | argyleink/open-props | MIT | spacing / shadow / motion ladders; our own values |
| Machine-checkable accessibility rules (image alt, button name, label, viewport) | dequelabs/axe-core | MPL-2.0 | re-implemented as regex/JSX checks (DES-005..008, DES-016); no rule files copied |
| WCAG 2.x relative luminance and contrast ratio | W3C WCAG 2.x | W3C document licence | the published formula, implemented in `color.py` |
| OKLab / OKLCH conversion matrices | Björn Ottosson, "A perceptual color space for image processing" (2020) | public domain / MIT | `color.py` |
| Always-on core rules + context-selected modules | cosai-oasis/project-codeguard | CC BY 4.0 | two-tier layout of `security_rules`; text is ours |
| FastAPI, React, Docker, JWT, password storage, CORS, headers guidance | OWASP Cheat Sheet Series, OWASP ASVS 5.0 | CC BY-SA 4.0 | paraphrased only; no sentences reused |
| Which Python calls are dangerous sinks (eval, shell=True, yaml.load, weak hashes, requests without timeout) | PyCQA/bandit | Apache-2.0 | checks re-written with `ast` |
| Pattern ideas: wildcard CORS, formatted SQL, insecure hash, React raw HTML | semgrep/semgrep-rules | Semgrep Rules License v1.0 | no YAML copied; checks written from the idea only |
| Spec / checklist / analyse-before-implement; lint -> reflect -> bounded repair rounds | github/spec-kit (MIT), Aider-AI/aider (Apache-2.0) | MIT / Apache-2.0 | `report.repair_prompt` and the 3-round loop the caller runs |
| Production checklist (config from env, health/readiness, migrations, logs to stdout) | 12factor.net, Kubernetes probe conventions | public | prod-readiness checks PRD-001..013 |
