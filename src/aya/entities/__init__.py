"""Entities — the rules that would hold even without this application.

Packets, identities and the crypto that binds them. Nothing here reads a
file, opens a socket, or knows a CLI exists. Nothing in this layer may import
from ``usecases`` or ``adapters``.
"""
