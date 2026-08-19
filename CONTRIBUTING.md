# Contributing

This repository holds two independently versioned Python projects: the `aya` CLI
and MCP server at the root, and the `aya-gateway` HTTP service under `gateway/`.
Each has its own lockfile and its own CI job, so a change to one does not
require running the other's checks.

## Contents

- [Tech stack](#tech-stack)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Verification](#verification)
- [Commit conventions](#commit-conventions)
- [Testing](#testing)
- [Submitting a change](#submitting-a-change)
- [Further reading](#further-reading)

## Tech stack

Python, managed with [`uv`](https://docs.astral.sh/uv/). Linting and formatting
are `ruff`, type checking is `mypy` in strict mode, and tests are `pytest`.
Releases are cut by `python-semantic-release` from commit messages.

```text
aya/
├── src/aya/       entities/, usecases/, adapters/, scheduler/ — see Architecture
├── tests/         pytest suite; every test runs against an isolated AYA_HOME
├── gateway/       separate project, separate lockfile, separate CI job
├── docs/          reference and design documents
├── skills/        Claude Code plugin skills
└── Makefile       the shortcuts used below
```

## Architecture

The package is laid out in layers, and dependencies point inward only.

| Layer | Holds | May import |
| ---- | ---- | ---- |
| `entities/` | `Packet`, `Identity`, `TrustedKey`, `Profile`, crypto | nothing else |
| `usecases/` | `relay_ops`, `ingest`, `triage`, `resolve`, `packet_view`, `pair`, `watch_chains`, `status` | `entities` |
| `adapters/` | `cli/`, `mcp_server`, `relay`, `clock`, `paths`, and the storage gateways | `usecases`, `entities` |
| `scheduler/` | a bounded subsystem, layered internally | — |

Two rules matter more than the rest, and `tests/test_architecture.py` fails if
either breaks:

- **Nothing below `adapters/` imports `typer`, `click`, `rich` or `mcp`.** A use
  case that can print or exit cannot be reused by the other surface, which is
  how the CLI and MCP implementations drifted apart in the first place.
- **The CLI and the MCP server do not import each other.** They are peers over
  the same use cases, not layers.

New behaviour goes in `usecases/`. The surfaces parse input and render results.
[`docs/architecture.md`](docs/architecture.md) has the full component map.

## Prerequisites

- **Python 3.12 or 3.13.** `pyproject.toml` requires `>=3.12`, and
  `.python-version` pins `3.12` for local work.
- **Python 3.14 does not work yet.** `coincurve` 21.0.0 publishes no `cp314`
  wheel, and its source build fails against `cffi` 2.0.0. Pass an explicit
  interpreter on a fresh install: `uvx --python 3.12 --from git+https://github.com/shawnoster/aya aya`
- **`uv`**, any recent version. Nothing in the repo pins a minimum.
- **Docker**, only if you want to build or run the gateway image locally. Lint,
  type check and tests all run without it.

## Setup

```bash
git clone https://github.com/shawnoster/aya.git
cd aya
uv sync
make install-hooks     # runs `uv run pre-commit install`
```

The pre-commit hooks run `ruff check --fix` and `ruff format`. They do **not**
run `mypy` or `pytest`, so a clean commit does not mean a passing build — run
the full check below before opening a pull request.

For the gateway:

```bash
cd gateway
uv sync --all-groups
```

Run the CLI without installing it globally with `uv run aya`. To put it on your
`PATH`, use `uv tool install .`.

## Verification

One command mirrors CI for the root project:

```bash
make check     # lint, then type-check, then test
```

The individual steps, and their gateway equivalents:

| Step | Root project | `gateway/` |
| ---- | ---- | ---- |
| Lint | `uv run ruff check src tests` | `uv run ruff check .` |
| Format | `uv run ruff format --check src tests` | `uv run ruff format --check .` |
| Types | `uv run mypy src` | `uv run mypy app` |
| Tests | `uv run pytest` | `uv run pytest` |

`mypy` runs strict with no per-module exclusions, so a new module cannot quietly
skip typing. Two error codes are enabled beyond `--strict`: `deprecated` (PEP
702) and `warn_unreachable`, which errors on any statement mypy proves cannot
execute. Note that `mypy` covers `src` only — `tests` is linted but not
type-checked.

`warn_unreachable` is the one flag whose correct response is sometimes *not* to
change the code. A runtime guard over data mypy only *believes* it knows the
shape of — a `cast` over `json.loads`, say — is load-bearing even when mypy
calls it dead. Annotate the local `object` so the guard is genuinely reachable
rather than suppressing the error; `--strict` implies `warn_unused_ignores`, so
a `# type: ignore[unreachable]` would also become a fresh error the day someone
turns the flag off.

## Commit conventions

Commit messages drive releases, so the type you choose picks the next version
number. `python-semantic-release` parses them on every push to `main`.

Use [Conventional Commits](https://www.conventionalcommits.org/), with the
changed subsystem as the scope:

```text
fix(aya): keep ANSI out of machine output
feat(gateway): add a health endpoint
chore(deps): bump cryptography to 50
docs(skills): pin aya refresh to Python 3.13
test(aya): cover the stdio transport
```

| Type | Effect on the version |
| ---- | ---- |
| `feat:` | minor |
| `fix:` | patch |
| `docs:`, `test:`, `chore:`, `ci:`, `refactor:` | none |
| Any type with `!`, or a `BREAKING CHANGE:` footer | major |

**Mark breaking changes explicitly.** A breaking change described only in prose
ships as a patch, and consumers pinned to a compatible range pick it up without
warning. Put a `!` after the type, or a `BREAKING CHANGE:` footer in the body:

```text
chore(deps)!: migrate to the mcp 2.0 server API

BREAKING CHANGE: requires mcp >= 2.0. Anything importing
aya.adapters.mcp_server against mcp 1.x now fails at import.
```

When a pull request is squash-merged, GitHub builds the commit message from the
title and the commit bodies. Check that a `BREAKING CHANGE:` footer survives
into the final message — editing it out silently downgrades the release.

## Testing

- **Every test runs against an isolated `AYA_HOME`.** An autouse fixture in
  `tests/conftest.py` points all data paths at a per-test temporary directory,
  because the suite used to write into a developer's real `~/.aya`, where
  ingest deletes packets older than seven days.
- **The crontab is faked too.** A second autouse fixture intercepts `crontab`
  invocations against a per-test in-memory crontab, because `install_scheduler`
  and `uninstall_scheduler` shell out to `crontab -l` and `crontab -` — a test
  exercising either without it deletes the `aya-scheduler-tick` entry belonging
  to whoever ran the suite. A crontab call the fixture does not model raises
  rather than faking success.
- **Freeze time at one seam.** `adapters/clock.py`'s `now()` is the only place
  that reads the wall clock. Patch that rather than `datetime`.
- **`RelayClient` takes an injectable `sleep`**, so retry-path tests do not
  spend real seconds waiting.
- **The layering rules are executable.** `tests/test_architecture.py` walks the
  AST of every module and fails CI on a violation, so a layering mistake is a
  test failure rather than a review comment.

## Submitting a change

1. Branch from `main`. No naming convention is enforced.
2. Make the change, with tests.
3. Run `make check`.
4. Open a pull request and fill in
   [the template](.github/PULL_REQUEST_TEMPLATE.md): summary, type of change,
   test plan, and any breaking changes.

The "Lint, type-check, test" job is a required status check on `main`. Do not
merge with `--admin` or force-push to `main` — the protections exist to be
waited on.

Commenting `/oc` or `/opencode` on an issue or a pull-request review triggers an
agent workflow, so expect a bot reply if you use those strings.

## Further reading

- [`docs/architecture.md`](docs/architecture.md) — the full component map.
- [`docs/commands.md`](docs/commands.md) — every CLI command, grouped.
- [`AGENTS.md`](AGENTS.md) — operating instructions for AI agents.
- [`gateway/README.md`](gateway/README.md) — the gateway's own deploy runbook.
- [`SECURITY.md`](SECURITY.md) — how to report a vulnerability.

Licensed MIT, same as the project.
