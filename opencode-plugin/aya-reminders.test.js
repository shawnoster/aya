import assert from "node:assert/strict"
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { test } from "node:test"

import plugin, { createReminders, DEBOUNCE_MS, formatMessage, runAya } from "./aya-reminders.js"

const ALERTS = [
  { id: "a1", message: "Reminder due: Check the PR" },
  { id: "a2", message: "PR approved" },
]

function harness({ pending = { alerts: ALERTS }, parents = {}, synthetic, delivered } = {}) {
  const calls = { aya: [], synthetic: [], log: [] }
  let clock = 1_000_000
  const handle = createReminders({
    session: {
      get: async ({ sessionID }) => ({ id: sessionID, parentID: parents[sessionID] }),
      synthetic: async (input) => {
        calls.synthetic.push(input)
        if (synthetic) await synthetic(input)
      },
    },
    runAya: async (args) => {
      calls.aya.push(args)
      if (args[1] === "delivered") return delivered ? delivered(args) : ""
      return typeof pending === "function" ? pending() : JSON.stringify(pending)
    },
    now: () => clock,
    log: (...args) => calls.log.push(args),
  })
  const succeeded = (sessionID) => handle({ type: "session.execution.succeeded", data: { sessionID } })
  return { calls, handle, succeeded, advance: (ms) => (clock += ms) }
}

test("default export is a V2 plugin definition", () => {
  assert.equal(plugin.id, "aya.reminders")
  assert.equal(typeof plugin.setup, "function")
})

test("posts pending alerts to the session, then marks exactly those IDs delivered", async () => {
  const { calls, succeeded } = harness()
  await succeeded("ses_a")

  assert.deepEqual(calls.aya[0], [
    "schedule", "pending", "--format", "json", "--skip-delivered", "--defer-receipt",
  ])
  assert.equal(calls.synthetic.length, 1)
  assert.equal(calls.synthetic[0].sessionID, "ses_a")
  assert.equal(calls.synthetic[0].resume, false)
  assert.equal(calls.synthetic[0].delivery, "queue")
  assert.deepEqual(calls.aya[1], ["schedule", "delivered", "a1", "a2"])
})

test("ignores events other than a finished turn", async () => {
  const { calls, handle } = harness()
  await handle({ type: "session.execution.started", data: { sessionID: "ses_a" } })
  assert.equal(calls.aya.length, 0)
})

test("skips subagent sessions without using up the debounce window", async () => {
  const { calls, succeeded } = harness({ parents: { ses_child: "ses_a" } })
  await succeeded("ses_child")
  await succeeded("ses_a")
  assert.deepEqual(calls.synthetic.map((s) => s.sessionID), ["ses_a"])
})

test("debounces checks within the window and resumes after it", async () => {
  const { calls, succeeded, advance } = harness()
  await succeeded("ses_a")
  advance(DEBOUNCE_MS - 1)
  await succeeded("ses_a")
  assert.equal(calls.synthetic.length, 1)
  advance(1)
  await succeeded("ses_a")
  assert.equal(calls.synthetic.length, 2)
})

test("does not mark delivered when posting fails, so the alert is offered again", async () => {
  const { calls, succeeded } = harness({
    synthetic: async () => {
      throw new Error("session removed")
    },
  })
  await succeeded("ses_a")
  assert.equal(calls.aya.some((args) => args[1] === "delivered"), false)
  assert.equal(calls.log.length, 1)
})

test("logs a failed delivered call instead of throwing", async () => {
  const { calls, succeeded } = harness({
    delivered: async () => {
      throw new Error("aya schedule delivered failed")
    },
  })
  await succeeded("ses_a")
  assert.equal(calls.synthetic.length, 1)
  assert.match(String(calls.log[0][0]), /could not mark them delivered/)
})

test("stays quiet when aya is not installed", async () => {
  const { calls, succeeded } = harness({ pending: () => null })
  await succeeded("ses_a")
  assert.equal(calls.synthetic.length, 0)
  assert.equal(calls.log.length, 0)
})

test("reports a broken aya instead of treating it as nothing pending", async () => {
  const { calls, succeeded } = harness({
    pending: () => {
      throw new Error("aya schedule pending failed: No such option: --skip-delivered")
    },
  })
  await succeeded("ses_a")
  assert.equal(calls.synthetic.length, 0)
  assert.match(String(calls.log[0][1]), /No such option/)
})

test("posts nothing when no alerts are pending", async () => {
  const { calls, succeeded } = harness({ pending: { alerts: [] } })
  await succeeded("ses_a")
  assert.equal(calls.synthetic.length, 0)
  assert.equal(calls.aya.length, 1)
})

test("formats a count, an instruction, and one line per alert", () => {
  assert.equal(
    formatMessage([{ id: "x", message: "" }, ...ALERTS.slice(1)]),
    "**aya scheduler**: 2 pending alert(s). Mention these to the user:\n- (no message)\n- PR approved",
  )
})

function withStubAya(script, fn) {
  const dir = mkdtempSync(join(tmpdir(), "aya-stub-"))
  if (script !== null) {
    writeFileSync(join(dir, "aya"), `#!/bin/sh\n${script}\n`)
    chmodSync(join(dir, "aya"), 0o755)
  }
  const previous = process.env.PATH
  process.env.PATH = dir
  return fn().finally(() => {
    process.env.PATH = previous
  })
}

test("runAya resolves stdout from a successful run", () =>
  withStubAya(`echo '{"alerts":[]}'`, async () => {
    assert.equal((await runAya(["schedule", "pending"])).trim(), '{"alerts":[]}')
  }))

test("runAya resolves null when aya is not on PATH", () =>
  withStubAya(null, async () => {
    assert.equal(await runAya(["schedule", "pending"]), null)
  }))

test("runAya rejects with aya's stderr when it fails", () =>
  withStubAya(`echo "No such option: --skip-delivered" >&2; exit 2`, async () => {
    await assert.rejects(runAya(["schedule", "pending"]), /schedule pending failed: No such option/)
  }))
