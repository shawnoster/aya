/**
 * aya-reminders — OpenCode plugin for proactive reminder and alert surfacing.
 *
 * Hooks into OpenCode's session.idle event to check for due aya reminders and
 * unseen alerts, then surfaces them via tui.toast.show and tui.prompt.append.
 *
 * Install:
 *   Files in ~/.config/opencode/plugins/ are auto-loaded at startup.
 *   Copy or symlink this file there, or run: aya schedule install
 *
 * Requires:
 *   - aya >= 1.42.0 on PATH
 *   - aya schedule install (crontab tick for background watch polling)
 */

// How many seconds to debounce idle events — avoids hammering aya on every
// brief pause. OpenCode fires session.idle fairly frequently.
const DEBOUNCE_SECONDS = 15

export const AyaRemindersPlugin = async ({ $ }) => {
  let lastChecked = 0

  /**
   * Run `aya schedule pending --format json` and return parsed output.
   * Returns null on any error (aya not on PATH, scheduler empty, etc.)
   */
  async function getPending() {
    try {
      const result = await $`aya schedule pending --format json`.text()
      if (!result.trim()) return null
      return JSON.parse(result)
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
     * OpenCode delivers all events through a single `event` handler.
     * Filter for session.idle to check pending reminders and alerts.
     */
    event: async ({ event }) => {
      if (event.type !== "session.idle") return

      const now = Date.now() / 1000
      if (now - lastChecked < DEBOUNCE_SECONDS) return
      lastChecked = now

      const pending = await getPending()
      if (!pending) return

      // Collect due reminders + unseen alerts
      const items = [
        ...(pending.due_reminders || []),
        ...(pending.alerts || []),
      ]

      if (items.length === 0) return

      const summary = items.map(formatItem).join("\n")

      // Inject into the next prompt so the agent sees it
      try {
        await event.publish({
          type: "tui.prompt.append",
          properties: {
            text: `\n\n---\n**aya scheduler**\n${summary}\n---`,
          },
        })
      } catch {
        // Fall back to a shell notification if prompt injection isn't available
        try {
          await $`notify-send "aya" ${summary}`.quiet()
        } catch {
          // best-effort — fail silently
        }
      }
    },
  }
}
