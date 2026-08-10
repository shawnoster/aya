"""Adapters — everything that touches the outside world.

Two kinds, deliberately in one ring (Clean Architecture's "Interface
Adapters"):

* **Driving** — ``cli`` and ``mcp_server``. Peers, not layers: each parses
  its own input, calls a use case, and renders the result. Neither may
  import the other.
* **Driven** — ``relay`` (Nostr), plus the persistence gateways ``paths``,
  ``atomic``, ``ledger``, ``outbox``, ``config``, ``credentials``, and the
  system integrations ``install`` and ``rewake``.
"""
