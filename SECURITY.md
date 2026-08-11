# Security policy

## Reporting a vulnerability

Report privately through
[GitHub's private vulnerability reporting](https://github.com/shawnoster/aya/security/advisories/new)
rather than opening a public issue.

This is a single-maintainer project, so expect a first response within a week
rather than within hours.

## Supported versions

Only the latest release on PyPI receives fixes. There are no maintained release
branches.

## In scope

- **Identity and packet handling** — the Ed25519 signing and DID verification in
  `entities/packet.py`, and the NIP-44 encryption in `entities/encryption.py`.
  A way to forge a signature, impersonate a DID, or read a packet without the
  recipient key is the most serious class of bug here.
- **Local state** — the profile holds private keys. It is written atomically
  under a lock at mode `0600`, and packet bodies are written the same way. A
  path that leaves either world-readable, or that lets one instance overwrite
  another's keys, is in scope.
- **Relay trust** — packets from unpaired senders must not be ingested without
  `--yes`, and a failed signature must be discarded rather than surfaced as
  trusted content.
- **The gateway** (`gateway/`) — bearer-token authentication on its endpoints.
  An unauthenticated path to an effect is in scope.
- **Workflow triggers** — `.github/workflows/opencode.yml` runs on an issue or
  pull-request-review comment containing `/oc` or `/opencode`. Because this
  repository is public, any GitHub user can trigger it, and the job has an
  `ANTHROPIC_API_KEY` and `id-token: write` in scope. A way to make that
  workflow leak a secret, or to run attacker-controlled code inside it, is in
  scope and is the most likely place for a real finding.

## Out of scope

- Relay operators seeing packet metadata. Packet bodies are encrypted, but a
  relay necessarily learns timing and recipient public keys. Relays are treated
  as untrusted transport, not as confidants.
- Anything requiring an attacker to already have read access to `~/.aya`. That
  directory holds private keys, and local filesystem compromise is outside the
  threat model.
- Denial of service against a public relay.
