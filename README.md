# Group 27: a verification gate for AI refactoring of json-c

json-c is a C library that reads JSON text. Its reader, `json_tokener_parse_ex`
in `json-c/json_tokener.c`, is a single function of about 1,100 lines. In this project an
AI (and, for comparison, a person) splits it into smaller functions, and an
automatic **gate** decides whether each rewrite still behaves exactly like the
original. The aim is a gate the AI cannot switch off or fake; what it does not
catch yet is listed in `oracle/README.md`.

## Layout

| Path | What it is | Who changes it |
|---|---|---|
| `json-c/` | json-c at commit `d2ce61e`, tagged `baseline` | Only rewrite PRs, and only `json-c/json_tokener.c` |
| `oracle/` | The gate's checks: old-vs-new comparison now; chunked feeding and fuzzing to come | Role A |
| `bughunt/` | Earlier bug hunt: 8 json-c bugs, reproducers and harnesses. Reference only | Nobody |

## Baseline

The reference version is json-c commit
[`d2ce61e`](https://github.com/json-c/json-c/commit/d2ce61eb214e) (2026-11-21),
tagged `baseline` in this repo. A rewrite passes when it gives the same answers
as this version on every input, including the known bugs listed in
`bughunt/README.md`. Fixing a bug counts as a change in behaviour.

## Working on this repo

- `main` holds the agreed starting point. Nobody commits to it directly.
- Each piece of work goes on its own branch, named `<role>/<topic>`
  (for example `a/oracle`, `b/agent-state-string`), and is merged by pull request.
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`.
