## What and why

<!--
One or two sentences on the problem, then what this does about it. Lead with the
motivation — the reviewer can read the diff, so do not narrate it.

AUTHORING NOTE (applies to AI authors especially): if you cannot state the
problem without describing the code, you are summarising the diff. Say what was
broken or missing, and for whom. "Every `make check` deleted the developer's
crontab entry" beats "adds an autouse fixture to conftest".
-->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Refactor / tech debt
- [ ] Docs / config only

## Related

<!-- Closes #N · Follow-up to #N · Jira key in brackets, e.g. [CSD-532] · or "none" -->

## Evidence

<!--
What proves this works, and how strongly. Name the check and its result.

Be explicit about the difference between:
  - `make check` passes                     — the suite agrees with itself
  - verified against the real thing         — a live run, with the output
  - not verified                            — say so, and why

AUTHORING NOTE: every claim here needs a command and its result, or an explicit
admission that it was not verified. Never imply verification you did not do; a
reviewer cannot tell the difference and will assume the stronger reading.

Two things that are easy to omit and worth more than a passing suite:
  - If a test previously asserted the buggy behaviour, say so. That is usually
    why the bug survived, and the reviewer needs to know an assertion changed
    rather than a new one appeared.
  - If the fix is only live after an install/deploy step, say that too. Merged
    is not the same as running.
-->

## Risk and scope

<!--
Keep the lines that apply, delete the rest — but keep one even when the answer
is reassuring. A reviewer who reads "checked, clean" spends no time re-deriving
what you already ruled out.

AUTHORING NOTE: "Deliberately out of scope" stops being optional the moment you
notice something. Quietly narrowing the work is worse than naming the cut and
letting the reviewer disagree with it.
-->

- **Behaviour change:** <!-- including API-stable ones a caller would still notice -->
- **Deliberately out of scope:** <!-- what you saw and chose not to fix, and why -->
- **Checked and found clean:** <!-- hypotheses ruled out, so nobody re-runs them -->

## Checklist

<!--
AUTHORING NOTE: do not tick a box you did not do. An unticked box with a
one-line reason is useful information; a ticked box that is false makes the
whole list worthless, including the boxes that were honest.
-->

- [ ] Conventional Commit title — see [commit conventions](https://github.com/shawnoster/aya/blob/main/CONTRIBUTING.md#commit-conventions)
- [ ] `make check` passes locally — lint, type-check, tests
- [ ] Tests cover the specific failure this fixes, not only the happy path
- [ ] Behaviour changes named above, including ones the API hides
- [ ] A `BREAKING CHANGE:` footer, if any, survives into the squash message
- [ ] No narration of *this* PR's bug left in code comments or docstrings
- [ ] No secrets, credentials, or personal data
