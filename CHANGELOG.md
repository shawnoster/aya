# Changelog

## [Unreleased]

### Fixed

- **The profile is written atomically, under a lock, at 0600.** `save()` was
  read-then-`write_text`, so a crash mid-write truncated the only copy of every
  instance private key, and two writers spanning a relay round-trip silently
  lost one side's changes. The scheduler already had lock + atomic-replace;
  those primitives now live in `aya/atomic.py` and both use them. The mode is
  applied before the rename, closing the window where the key file existed at
  the umask default.
- **Packet ledgers moved out of the key file** into `ledger.json`, with their
  own lock and TTL. Every poll used to rewrite the profile just to advance a
  cursor — the highest-frequency write against the highest-value payload. The
  profile is now only rewritten when it actually changes. Existing profiles
  migrate on first save; entries with unparseable timestamps are kept rather
  than silently dropped, since dropping one causes the packet to be re-ingested.
- **`publish` no longer sleeps after its final retry.** A fully rate-limited
  relay waited out one last backoff (up to the 60s cap) with no attempt left
  to make, delaying an already-failed publish. Found once the retry loop
  became testable.
- **`aya relay add --first` now reorders a relay that is already present.** It
  returned "already in default_relays — no change", so "make this primary" was
  a silent no-op whenever the relay existed further down the list.
- **Polling no longer fails silently.** `receive` and `inbox` (CLI and MCP)
  now return `instance`, `relays`, and `relay_reachable` alongside `packets`.
  An empty result used to be indistinguishable from polling the wrong
  identity or an unreachable relay — all three returned `{"packets": []}`
  with exit 0. `inbox` also gained the relay error handling `receive`
  already had, instead of letting the exception escape.
- **`--as` no longer defaults to the literal `default` instance.** On a
  profile holding both a real instance and a leftover `default` stub from
  `aya init`, every command silently acted as the stub — a different Nostr
  keypair, so every poll came back empty. Omitting `--as` now resolves the
  primary instance (`aya use`, else the sole instance, else the sole
  non-`default` one) and *errors* when the choice is ambiguous rather than
  guessing. The MCP tools no longer default `instance` to `"default"`.
- **`aya send` no longer ships an empty packet.** The body came from
  `sys.stdin.read()` with no guard and no mention in `--help`; with no pipe
  it hung on a terminal or sent an empty body in a script. Missing or
  whitespace-only bodies now exit 2 and name every way to supply one.
- **`aya receive` no longer aborts mid-poll without a terminal.** The
  per-packet confirm had no non-interactive fallback. It now exits 2 naming
  `--auto-ingest`/`--yes`, and only when packets actually need confirming.

### Added

- **`aya pair` now makes the relay it paired over the primary relay.** Pairing
  proves both sides can reach that relay, but the fact was discarded — so on a
  fresh install (where `aya init` seeds only public relays) every later
  `send`/`receive` needed `--relay` to rediscover it. Existing relays are kept
  as fallbacks. This is what made the flag feel mandatory.
- `aya sent` — the outbound log, counterpart to `aya inbox`. `aya send` left
  no local trace at all, so "did that actually go out?" was unanswerable
  (`aya packets` lists received packets only). Entries record recipient,
  intent, event id, and per-relay delivery, and are pruned after 7 days.
  `--failed` filters to packets some relay rejected. Sent bodies are now
  persisted too, so `aya read <id>` works on them. Also exposed as the
  `aya_sent` MCP tool.
- **Per-relay delivery reporting on `send` and `ack`.** `publish` succeeds
  when *any* relay accepts, so a partial failure was invisible — if the peer
  polled only the rejecting relay, the packet was silently undeliverable
  despite a green checkmark. Both commands now list each relay with its
  outcome, warn when delivery was partial, and return `relays_ok` /
  `relays_failed` under `--format json` and from the MCP tools.
- `aya whoami` — active local identity, how it was resolved, every
  registered instance, every trusted peer, and the relay list. Previously
  the only way to enumerate instances was to pass a bad `--as` and read the
  error.
- `aya use <label>` — set the instance commands act as when `--as` is omitted.
- `aya send --message/-m` — supply a markdown body inline. `--help` now
  documents all four body sources (`--seed --opener`, `-m`, `--files`, stdin).
- `relay` parameter on `aya_send`, `aya_receive`, `aya_inbox`, and `aya_ack`,
  matching the CLI's `--relay`. There was previously no way to override the
  relay over MCP at all.
- `from_label` on `aya_inbox` results, removing the `aya_relay_status`
  round-trip previously needed to map a sender DID to a human label.

### Changed

- `aya_inbox` and `aya_receive` return `{"packets": [...], ...}` instead of a
  bare list, matching the CLI. **Breaking** for callers that indexed the
  result directly.
- `aya relay status` reports the resolved instance label rather than echoing
  the caller's argument.

### Removed

- `aya pack` — `aya send` is the canonical pack-and-publish flow. The pack
  command had no callers in skills, hooks, or MCP — its help even redirected
  users to `send`. If you need to build a packet without publishing, use
  `aya send --dry-run` or build the JSON manually and use `aya send-raw`.
- `aya show` — collapsed into `aya read`. Pass `--panel` to `read` for the
  boxed display the old `show` produced. The MCP `aya_show` tool is removed
  with the same migration: `aya_read(meta=true)` returns the structured
  fields, and reading the packet file at `~/.aya/packets/<id>.json` gives
  the full signed envelope.
- `aya schedule check` — partial reimplementation of `pending` and `alerts`.
  Use `aya schedule pending` (the SessionStart payload) for due reminders
  + actionable alerts, or `aya schedule alerts [--mark-seen]` for the
  alert queue alone.
- `aya schedule poll` — replaced by `aya schedule tick`, which already calls
  `run_poll` internally. The command had been documented as legacy since the
  unified tick refactor; nothing in skills, hooks, or the system crontab
  calls it.
- `aya profile` — the persistent assistant profile is created and touched by
  `aya init` and `aya pair`; the inspect-only verb had no callers in skills,
  hooks, or the MCP surface. To inspect a profile, read `~/.aya/profile.json`
  or use `aya status`.
- Hidden deprecated flags `--label` (alias for `--peer` on `trust` and `pair`)
  and `--instance` (alias for `--as` on `pack`, `send`, `send-raw`, `ack`,
  `receive`, `inbox`, `pair`). They had been emitting warnings since the
  rename in #230; switch any remaining call sites to the canonical flag names.

### Fixed

- `aya receive` no longer drops pending packets via a stale `since` cursor
  (#247). The previous behaviour persisted a per-instance "last checked"
  timestamp and used it as the relay query lower bound, which permanently
  excluded packets that had arrived before the cursor but hadn't been
  ingested yet (e.g. when a prior receive crashed). Deduplication now
  uses the local `ingested_ids` list/dedup cache against the relay's natural 7-day
  TTL window, so unfinished receives can recover on the next run.
- Pin `coincurve<21` to avoid source build failure on Python 3.14 — coincurve 21.0.0 has a broken
  `hatch_build.py` that looks for cffi's LICENSE file during build, but cffi 2.0.0 changed sdist
  packaging so that file no longer exists in the expected location (closes #101). The pin will be
  lifted when coincurve ships cp314 wheels or cffi fixes its sdist packaging.

### Changed

- Refactor: packet ingestion logic lifted out of `cli.py` into a shared
  `aya.ingest` module (#245). Both the CLI `aya receive` command and the
  MCP `aya_receive` tool now share the same code path. User-facing
  behaviour is unchanged.

### Removed

- `aya bootstrap` and `aya reset` commands — workspace scaffolding is no longer part of aya's
  responsibilities. The guild workspace is the source of truth; aya is a tool the workspace calls.
- `scripts/bootstrap.py` — standalone workspace scaffolder script
- `templates/` directory — stale `AGENTS.md` and `CLAUDE.md` templates
- `framework/scripts/` directory — `scheduler.py`, `status_check.py`, `assistant_profile.py`,
  `watcher_daemon.py` (none were imported by the CLI; workspace content only)
- `skills/` directory — skill `SKILL.md` files belong in the user's guild workspace, not in aya

### Changed

- Renamed Python package from `ai-assist` to `aya`; CLI binary renamed from `assist` to `aya`
- Updated all internal imports, user-facing messages, docs, and tests accordingly
