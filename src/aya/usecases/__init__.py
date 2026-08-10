"""Use cases — what aya does, expressed once per operation.

Orchestrates entities to carry out an operation: send a packet, poll for new
ones, pair with a peer. Errors are raised as types the adapters translate.

The rule, as ``tests/test_architecture.py`` enforces it:

* May import ``entities``.
* May import **driven** adapters — ``clock``, ``paths``, ``relay``,
  ``profile_store`` and the other gateways. Reaching for those directly is
  the deliberate choice for a codebase this size; inverting them behind ports
  would buy indirection this application does not need.
* May **not** import a **driving** adapter (``cli``, ``mcp_server``), and may
  not import ``typer``, ``rich`` or ``mcp``. A use case that can print or
  exit cannot be reused by the other surface — which is exactly how the two
  implementations drifted apart before this layer existed.
"""
