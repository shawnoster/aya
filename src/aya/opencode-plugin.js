/**
 * aya-reminders — OpenCode plugin for proactive reminder and alert surfacing.
 *
 * Subscribes to OpenCode's event stream and, when a top-level session finishes
 * a turn, checks aya for pending alerts (due reminders arrive as alerts via
 * `aya schedule tick`). Anything pending is added to that session as a
 * synthetic message, so the agent sees it on the next prompt.
 *
 * Delivery is confirmed in two steps: `pending --defer-receipt` claims alerts
 * without marking them delivered, and `aya schedule delivered` marks them once the
 * message is posted. If posting fails, the claim expires and the alert is
 * offered again rather than lost.
 *
 * Targets the OpenCode V2 plugin API. The default export is a plain
 * definition object, so the file loads without an `@opencode/plugin` install.
 *
 * Install:
 *   Files in ~/.config/opencode/plugins/ are auto-loaded at startup.
 *   Copy or symlink this file there, or run: aya schedule install
 *
 * Requires:
 *   - OpenCode V2 (tested on 2.0.27)
 *   - aya >= 2.3.0 on PATH, for `pending --skip-delivered --defer-receipt`
 *     and `schedule delivered`
 *   - aya schedule install (crontab tick for background watch polling)
 */

import { execFile } from "node:child_process"

// Spawning aya costs a process per turn; back-to-back turns rarely change what
// is pending.
export const DEBOUNCE_MS = 15_000
const AYA_TIMEOUT_MS = 10_000

const PENDING_ARGS = ["schedule", "pending", "--format", "json", "--skip-delivered", "--defer-receipt"]

/**
 * Run `aya` with the given arguments and resolve to its stdout, or to null
 * when aya is not on PATH. Any other failure rejects, so a broken aya is
 * reported instead of reading as "nothing pending".
 */
export function runAya(args, signal) {
  return new Promise((resolve, reject) => {
    execFile("aya", args, { signal, timeout: AYA_TIMEOUT_MS }, (error, stdout, stderr) => {
      if (!error) return resolve(stdout)
      if (error.code === "ENOENT") return resolve(null)
      const detail = stderr.trim() || error.message
      reject(new Error(`aya ${args.slice(0, 2).join(" ")} failed: ${detail}`))
    })
  })
}

export function formatMessage(alerts) {
  const lines = alerts.map((alert) => `- ${alert.message || "(no message)"}`)
  return [
    `**aya scheduler**: ${alerts.length} pending alert(s). Mention these to the user:`,
    ...lines,
  ].join("\n")
}

/**
 * Build the event handler. Everything with a side effect comes in through
 * `deps`, so the decision logic runs under test without OpenCode or aya.
 *
 * @param {object} deps
 * @param {object} deps.session  `ctx.session`: needs `get` and `synthetic`
 * @param {(args: string[]) => Promise<string | null>} deps.runAya
 * @param {() => number} [deps.now]
 * @param {(...args: unknown[]) => void} [deps.log]
 * @returns {(event: { type: string, data?: { sessionID?: string } }) => Promise<void>}
 */
export function createReminders({ session, runAya, now = Date.now, log = console.error }) {
  let lastChecked = -Infinity

  async function surface(sessionID) {
    const info = await session.get({ sessionID })
    if (info.parentID) return

    const time = now()
    if (time - lastChecked < DEBOUNCE_MS) return
    lastChecked = time

    const stdout = await runAya(PENDING_ARGS)
    if (!stdout?.trim()) return
    const alerts = JSON.parse(stdout).alerts ?? []
    if (alerts.length === 0) return

    await session.synthetic({
      sessionID,
      text: formatMessage(alerts),
      description: "aya reminders and alerts",
      delivery: "queue",
      resume: false,
    })

    try {
      await runAya(["schedule", "delivered", ...alerts.map((alert) => alert.id)])
    } catch (error) {
      log("aya-reminders: posted alerts but could not mark them delivered; they will be offered again:", error)
    }
  }

  return async (event) => {
    if (event.type !== "session.execution.succeeded") return
    try {
      await surface(event.data.sessionID)
    } catch (error) {
      log("aya-reminders:", error)
    }
  }
}

export default {
  id: "aya.reminders",
  setup(ctx) {
    const controller = new AbortController()
    const handle = createReminders({
      session: ctx.session,
      runAya: (args) => runAya(args, controller.signal),
      log: (...args) => {
        if (!controller.signal.aborted) console.error(...args)
      },
    })

    void (async () => {
      for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
        void handle(event)
      }
    })().catch((error) => {
      if (!controller.signal.aborted) console.error("aya-reminders: event stream ended:", error)
    })

    return () => controller.abort()
  },
}
