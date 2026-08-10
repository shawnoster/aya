"""Use cases — what aya does, expressed once per operation.

Orchestrates entities to carry out an operation: send a packet, poll for new
ones, pair with a peer. Free of presentation: no printing, no exit codes, no
Typer or MCP types. Errors are raised as types the adapters translate.

May import ``entities``. May not import ``adapters`` — except for the
persistence gateways it is currently handed directly, which is tracked debt.
"""
