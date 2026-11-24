# ci: the gate on every pull request

Every pull request runs these checks (`.github/workflows/gate.yml`). Once
branch protection is on, a PR merges into `main` only when `paths` and `gate`
pass and a teammate approved it. `fuzz` is not required: a short run can miss
what a long one finds, so passing it says little; but a failure is always a
real difference, so treat it as one.

| Check | What it does | Fails when |
|---|---|---|
| `paths` | `ci/check_paths.py`: which files the PR changes | the PR breaks a path rule (below) |
| `gate` | `oracle/check.py` on the PR's `json-c/json_tokener.c` | the tokener behaves differently from the baseline, crashes, leaks, is much slower, or does not build (see `oracle/README.md`) |
| `fuzz` | rewrite PRs only: `fuzz/fuzz.py` for 5 minutes (not a required check) | the fuzzer found an input where the rewrite answers differently, crashes, leaks or hangs; the input is on the run's summary page (see `fuzz/README.md`) |

CI does not run the checker's and the CI's own tests (`oracle/tests`,
`ci/tests`). They test the gate, not a rewrite, and on a PR that changes the
gate they would run that PR's own version, so they could not stop it anyway:
the code owner's review does. Run them locally before changing the gate:
`python3 -m pytest oracle/tests ci/tests`.

To see why a check failed, open the PR's **Checks** tab. The `gate` job puts its
full report (smallest differing inputs, baseline vs candidate answers) on the
run's summary page.

## Path rules

1. `bughunt/` is read-only.
2. In `json-c/`, only `json-c/json_tokener.c` may change, and it may not be
   deleted or renamed.
3. A PR that changes `json-c/json_tokener.c` (a **rewrite PR**) changes nothing
   else.

Rule 3 is what keeps a rewrite from weakening its own check: a rewrite PR
carries no change to `oracle/`, `ci/` or `.github/`, so it is judged by `main`'s
checker and workflow. Any PR that changes those needs Role A's approval
(`.github/CODEOWNERS`).

## Submitting a rewrite (Role B)

1. `git switch main && git pull`, then `git switch -c b/<method>-<what>`, for
   example `b/agent-state-string`.
2. Change only `json-c/json_tokener.c`. Keep every public function
   (`json_tokener_parse_ex`, `json_tokener_new`, ...) with the same name and
   signature; new helper functions inside the file are fine, new files are not.
3. Optional, faster than waiting for CI: `python3 oracle/check.py`.
4. Push and open a PR into `main`. Every push reruns the checks.
5. When all three checks pass, any teammate can approve and merge.

Each failed run is a data point for the report (times blocked, what caught it),
so keep failed attempts as commits on the branch rather than rewriting history.

## Branch protection

`ci/protect-main.sh` turns it on for `main`: PR only, 1 approval (from a code
owner where one applies), the three checks passing on an up-to-date branch, new
pushes dismiss approvals, and the rules apply to admins too.

Before running it, add a second owner (for example Role C) to the `*` line in
`.github/CODEOWNERS`: GitHub does not let anyone approve their own PR, so with a
single owner, Role A could never merge a change to the gate.

## Tested on GitHub

Throwaway PRs, closed after the run (when CI still ran the self-tests):

| PR | Change | paths | gate | self-test |
|---|---|---|---|---|
| #3 | comment added to `json_tokener.c` | pass | pass | pass |
| #4 | quietly fixes bug 4 | pass | **fail**: 256 of 98,658 checks differ, strict configs only | pass |
| #5 | fixes bug 4 **and** makes the checker always pass | **fail**: `oracle/compare.py` may not change in a rewrite PR | pass (the weakened checker says so) | **fail** |

`ci/protect-main.sh` has not been run against the real repository yet.

## Known gaps

- Not yet run on GitHub: the `fuzz` job, and the `de_DE.UTF-8` locale the
  gate builds since iteration 2 of the gate review. They need clang with
  libFuzzer and glibc's locale sources (the `locales` package) on the
  runner; a missing one shows as a checker error, not as a pass.

- The workflow file is taken from the PR itself, so a PR that edits it can
  change what runs. That is closed by `CODEOWNERS` plus branch protection, not
  by the workflow: such a PR needs Role A's approval.
- The anti-cheat check (`oracle/cheats.py`, run by the `gate` job) reads the
  candidate's source and symbols; what it cannot see is listed under Known
  gaps in `oracle/README.md`.
