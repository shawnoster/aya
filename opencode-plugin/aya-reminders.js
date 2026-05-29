/**
 * aya-reminders — OpenCode plugin for proactive reminder and alert surfacing.
 *
 * Hooks into OpenCode's session.idle event to check for due aya reminders and
 * unseen alerts, then surfaces them via tui.toast.show (non-blocking) and
 * tui.prompt.append (injected into the next user prompt).
 *
 * Install:
 *   Copy or symlink this file to ~/.config/opencode/plugins/aya-reminders.js
 *   Or run: aya schedule install --opencode  (when supported)
 *
 * Requires:
 *   - aya >= 1.41.0 on PATH
 *   - aya schedule install (crontab tick for background watch polling)
 */

import { execSync } from "child_process"

// How many seconds to debounce idle events — avoids hammering aya on every
// brief pause. OpenCode fires session.idle fairly frequently; we only want
// to check once per quiet window.
const DEBOUNCE_SECONDS = 15

export const AyaRemindersPlugin = async ({ client }) => {
  let lastChecked = 0

  /**
   * Run `aya schedule pending --format json` and return parsed output.
   * Returns null on any error (aya not on PATH, scheduler empty, etc.)
   */
  function getPending() {
    try {
      const raw = execSync("aya schedule pending --format json 2>/dev/null", {
        encoding: "utf8",
        timeout: 5000,
      })
      if (!raw.trim()) return null
      return JSON.parse(raw)
    } catch {
      return null
    }
  }

  /**
   * Format a single reminder or alert into a short human-readable string.
   */
  function formatItem(item) {
    const msg = item.message || item.msg || "(no message)"
    if (item.type === "reminder") {
      return `⏰ Reminder: ${msg}`
    }
    return `🔔 Alert: ${msg}`
  }

  return {
    /**
     * session.idle fires when OpenCode detects the session has gone quiet.
     * We use it as the trigger to check for due reminders and alerts.
     */
    "session.idle": async () => {
      const now = Date.now() / 1000
      if (now - lastChecked < DEBOUNCE_SECONDS) return
      lastChecked = now

      const pending = getPending()
      if (!pending) return

      // Collect due reminders + unseen alerts
      const items = [
        ...(pending.due_reminders || []),
        ...(pending.alerts || []),
      ]

      if (items.length === 0) return

      // Show a toast for each item (non-blocking, shows in TUI status bar)
      for (const item of items) {
        try {
          await client.event.publish({
            type: "tui.toast.show",
            properties: {
              message: formatItem(item),
              // "warn" level shows in amber — visible but not alarming
              level: item.type === "reminder" ? "warn" : "info",
            },
          })
        } catch {
          // tui.toast.show may not be available in all OpenCode versions — fall through
        }
      }

      // Also inject into the next prompt so the agent can act on it
      const summary = items.map(formatItem).join("\n")
      try {
        await client.event.publish({
          type: "tui.prompt.append",
          properties: {
            text: `\n\n---\n**aya scheduler**\n${summary}\n---`,
          },
        })
      } catch {
        // tui.prompt.append may not be available — toast-only fallback is fine
      }
    },
  }
}
