# Templates

PII-free starting points. Copy what you need into the live tree.

| Template | Copy to | What it is |
|---|---|---|
| `PROFILE.example.md` | `profiles/<persona>/PROFILE.md` | The shape of the generated profile aggregate. Usually you do not need this - `/profile-build` generates it. |
| `../config/profiles.example/inputs.example.yaml` | `profiles/inputs.yaml` | Your preferences, locations, dealbreakers. **Start here.** |
| `CV_PATTERN.tex` | generator input | LuaLaTeX contract: header fixed, summary first, remaining sections dynamic |
| `REPORT_INDEX.example.json` | `reports/<persona>/YYYY-MM-DD/jobs-YYYY-MM-DD-HH-MM.json` | Example sidecar schema; `emphasis_signals` is per job |
| `FACT_CATALOG.example.json` | generator input | Example flat `facts[]` catalog with `summary:0`, weights, owners, and composite IDs |
| `CV_PLAN.example.json` | generator output | Example `cv-plan/v1` with `section_order` and `order_reason` |
| `CV_VERDICT.example.json` | verifier output | Example `cv-verdict/v1` |

## CV contract

`CV_PATTERN.tex` is a LuaLaTeX generator template.

- `@@HEADER@@` is replaced with `\CVHeader{name}{headline}{contact}`. The contact string includes tool-owned location from `profiles/inputs.yaml` with persona fallback.
- `@@SECTIONS@@` is replaced with sections rendered in `cv_plan.section_order`.
- `summary` is always first and must be selected verbatim from `summary:0`; never rewritten or duplicated from a bullet.
- Remaining sections are `skills`, `experience`, `projects`, `education`.
- Default order: `summary`, `skills`, `projects`, `experience`, `education`.
- `hands_on` order: `summary`, `projects`, `skills`, `experience`, `education`.
- `academic`/`research` order: `summary`, `education`, `skills`, `projects`, `experience`.
- Conflicting `hands_on` and `academic`/`research` signals use default order.
- Allowed `emphasis_signals`: `hands_on`, `production`, `research`, `academic`, `leadership`, `cloud`, `security`, `data`.
- Bullet facts may include `owner`; owned bullets must stay under that project or experience entry.
- Plans must include every supplied content fact; deterministic trimming happens only after an approved plan overflows a junior page target.

CV output lands in `reports/<persona>/<date>/Customized_CV/<company-slug>/<name>.{pdf,tex,log}`. LuaLaTeX is required for PDF; `/generate-cv --render-only` writes `.tex` only. Junior overflow also writes `<plan>.trimmed.json` and `trim-manifest-job<N>.json` next to the scratch plan.

Fact catalog IDs are resolved from `fact_catalog.facts[]`. Project and experience
entries use flat composite IDs such as `project:0:name`, `project:0:detail`,
`experience:0:heading`, and `experience:0:detail`.

## Setting up from scratch

```bash
mkdir -p profiles
cp config/profiles.example/inputs.example.yaml profiles/inputs.yaml
$EDITOR profiles/inputs.yaml
```

Then put a resume in `resumes/` and run `/profile-build` inside OpenCode.

## What never goes in here

Anything personal. The templates are tracked, the live files are not, and
`python3 tools/check_repo.py` fails the build if a personal file is tracked or
if a committed prompt contains a personal identifier.