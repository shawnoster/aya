# Command reference

Every `aya` command, grouped by what it acts on. Run `aya <command> --help` for
flags. The six commands you need most often are in the
[README](../README.md#commands).

## Contents

- [Identity and pairing](#identity-and-pairing)
- [Sending packets](#sending-packets)
- [Receiving packets](#receiving-packets)
- [The local packet store](#the-local-packet-store)
- [Reminders, watches and recurring jobs](#reminders-watches-and-recurring-jobs)
- [Scheduler installation and internals](#scheduler-installation-and-internals)
- [Relays](#relays)
- [Workspace](#workspace)
- [Servers and internal hooks](#servers-and-internal-hooks)

Two flags recur across the relay commands:

- `--as <label>` picks which local identity to act as. Omit it and aya resolves
  the primary instance, failing with the candidates listed if the choice is
  ambiguous. A wrong identity polls an unrelated keypair and looks exactly like
  an empty inbox.
- `--relay <url>` **replaces** the configured relay list for that one call. It
  does not narrow the list, so there is no fallback if that relay is down. To
  change the list permanently, use `aya relay add --first`.

## Identity and pairing

| Command | What it does |
| ---- | ---- |
| `aya version` | Show the installed aya version |
| `aya whoami` | Show the active local identity, all instances, and trusted peers |
| `aya use` | Set which instance commands act as when `--as` is omitted |
| `aya init` | Generate an identity keypair for this instance |
| `aya pair` | Pair two instances via a short-lived relay code |
| `aya trust` | Manually trust a decentralized identifier (DID) |

## Sending packets

| Command | What it does |
| ---- | ---- |
| `aya send` | Build, sign, and publish a knowledge packet (body from `-m`, `--files`, `--seed --opener`, or stdin) |
| `aya send-raw` | Publish a pre-built packet file to a Nostr relay |
| `aya ack` | Acknowledge a received packet, sending a reply back |
| `aya sent` | List packets you have sent, with per-relay delivery status (`--failed` to filter) |

Exit code 0 means at least one relay accepted the packet, which is not the same
as the peer receiving it. Check `relays_failed`, or run `aya sent --failed`.

## Receiving packets

| Command | What it does |
| ---- | ---- |
| `aya inbox` | List pending, un-ingested packets |
| `aya receive` | Review and ingest packets from the relay |
| `aya drop` | Drop a packet from inbox view so it stops resurfacing |

`aya inbox` does not ingest, so `aya read` and `aya ack` will not find a packet
that has only been listed. Run `aya receive --auto-ingest` first.

## The local packet store

| Command | What it does |
| ---- | ---- |
| `aya read` | Read the body of a stored packet (`--meta` for headers, `--panel` for a boxed display) |
| `aya packets` | List stored packets, received and sent, newest local write first |

## Reminders, watches and recurring jobs

| Command | What it does |
| ---- | ---- |
| `aya schedule remind` | Add a one-shot reminder |
| `aya schedule watch` | Add a polling watch (GitHub pull request, Jira ticket or query, CI checks) |
| `aya schedule recurring` | Add a persistent recurring session job |
| `aya schedule list` | List scheduled items |
| `aya schedule snooze` | Snooze a reminder until a given time |
| `aya schedule dismiss` | Dismiss a scheduled item or alert (prefix match is enough) |
| `aya schedule alerts` | Show alerts from the background watcher |

## Scheduler installation and internals

| Command | What it does |
| ---- | ---- |
| `aya schedule install` | Install scheduler integrations — a crontab entry plus Claude Code hooks |
| `aya schedule uninstall` | Remove scheduler integrations |
| `aya schedule status` | Scheduler overview — watches, reminders, deliveries |
| `aya schedule tick` | Run one scheduler cycle, polling watches and expiring alerts (the crontab entry calls this) |
| `aya schedule pending` | Show unclaimed alerts and session crons (the SessionStart hook reads this) |
| `aya schedule activity` | Record user activity, resetting the idle back-off timer |
| `aya schedule is-idle` | Check whether the session is currently idle |

## Relays

| Command | What it does |
| ---- | ---- |
| `aya relay list` | List configured relays |
| `aya relay add` | Add a relay to the default list (`--first` makes it primary) |
| `aya relay remove` | Remove a relay from the default list |
| `aya relay status` | Show relay health and identity info |

## Workspace

| Command | What it does |
| ---- | ---- |
| `aya status` | Workspace readiness check — systems, schedule, focus |
| `aya context` | Build a context block from workspace state |
| `aya config show` | Show the current workspace configuration |
| `aya config set` | Set a workspace configuration value |
| `aya log show` | Show daily notes |
| `aya log append` | Append to daily notes |
| `aya log auto` | Enable auto-logging of session notes |

## Servers and internal hooks

| Command | What it does |
| ---- | ---- |
| `aya mcp-server` | Start the MCP server over stdio, for Claude Code and other MCP clients |
| `aya hook crons` | Internal, wired by `aya schedule install`: turn active recurring schedules into Claude Code `CronCreate` instructions |
| `aya hook watch` | Internal, wired by `aya schedule install`: poll due watches and emit `asyncRewake` on change |
