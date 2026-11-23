---
description: Build or refresh a search persona from the resumes in resumes/ and the preferences in profiles/inputs.yaml
---

# /profile-build - Build or refresh a persona

Turns the resumes in `resumes/` plus the user's preferences into a persona:
a machine-readable file of derived facts, each backed by a line of a resume.

## Usage

- `/profile-build` - guided: choose which CVs to use, then name the persona
- `/profile-build <name>` - guided build or rebuild of persona `<name>`
- `/profile-build --check` - validate without writing

## Steps

### Step 0: Resolve the name target

If an argument was given, it is the target persona name. Read
`profiles/index.json` (`personas` keys) and the `profiles/*/profile.yaml`
directories. If the name already exists this is a **rebuild**; otherwise it is
a **new persona**. The chosen name becomes `profiles/<name>/`, is stored as
`active_persona` on finalize, and is the value passed later to
`/find-jobs --persona <name>`.

### Step 1: List available CVs

```bash
python3 tools/extract_resume.py --list
```

This prints every CV in `resumes/` with its slug, sha256 and whether an
extracted cache exists. It writes nothing. Cache files without a matching
source CV are stale and are not offered as choices.

### Step 2: Choose which CVs to include

Ask the user which resume slugs this persona should cover (multi-select,
at least one). Only selected CVs are used; every other CV stays out of this
persona. Two discovered CVs that share a slug is a collision - ask the user
to rename one before continuing.

### Step 3: Choose the persona name

Ask the user for the persona name (lowercase kebab-case). Suggest the variant
segment of the first selected CV's filename as the default. If the name
already exists, say "(rebuild)" and require explicit confirmation before
overwriting. This name is what the user later passes to
`/find-jobs --persona <name>`.

### Step 4: Extract only the selected CVs

```bash
python3 tools/extract_resume.py <selected-file> ...
```

Extract only the files chosen in Step 2 into `resumes/extracted/`.

### Step 5: Read the sources

Read, in parallel:

- only the extracted text of the selected CVs in `resumes/extracted/`
- `profiles/inputs.yaml`

Do **not** read the PDF directly, and do not read CVs that were not selected.

### Step 6: Write the persona file

Write `profiles/<persona>/profile.yaml` following the schema of the
existing persona file. The rules that matter:

- **Every fact carries evidence.** `source: "resume:<slug>#L11,L18-19"`.
- **Only selected CVs.** Every `source:` slug must be one of the CVs chosen
  in Step 2.
- **Never invent.** Only state what the resume says.
- **Target roles come from the resume.** Order them by how strongly the
  resume supports them; priorities are integers.
- **Skills carry a weight.** `primary`/`secondary`/`weak`.
- **Record conflicts.** If two selected CVs disagree about a fact, add it
  to `conflicts` rather than picking one.
- **Record all selected CVs** under `resumes:` with `slug`, `file`,
  `extracted_text`, `sha256`.

### Step 7: Finalize

```bash
python3 tools/profile_build.py --persona <persona> --finalize
```

This validates the file (slug shape, distinct resume slugs, every evidence
slug belongs to this persona's `resumes:` list), refreshes
`profiles/index.json`, and regenerates `profiles/<persona>/PROFILE.md`. If
it reports problems, fix the persona file and run again. Do not report
success while problems remain. This sets `<persona>` as `active_persona`.

### Step 8: Report

Tell the user:

- which persona was built and from which resume(s)
- the target roles, in priority order
- the primary skills
- anything that needs their decision (conflicts, missing fields)
- the literal command to search: `/find-jobs --persona <persona>`

## Notes

- The user's own preferences live in `profiles/inputs.yaml` and are never
  written here. This file holds only what the resumes say.
- `profiles/<persona>/PROFILE.md` is generated from both files. The
  `## User Notes` section at the bottom of it belongs to the user and is
  preserved when the aggregate is rebuilt.
