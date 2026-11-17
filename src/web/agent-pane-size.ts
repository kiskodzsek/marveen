// The size every agent tmux session starts with (new-session -x/-y).
//
// Why (card 0db274d2, Klodel 45908, session-stuck 45907): a detached new-session
// without -x/-y starts at tmux's default 80 columns. At that width Claude Code
// cuts its footer with a trailing `…` (`... · 1 monitor · ↓ to mana…`), the pane
// classifier read the kernel pane 'unknown', and four messages waited 10+
// minutes. Klodel's hand fix on 2026-11-17 resized every agent-* window to
// 120x30, and delivery resumed; a context-guard restart then started the
// session at 80 columns again. pane-state.ts now also accepts the cut footer;
// this keeps it from being cut in the first place.
export const AGENT_PANE_COLS = 120
export const AGENT_PANE_ROWS = 30
export const AGENT_PANE_SIZE_ARGS: readonly string[] = ['-x', String(AGENT_PANE_COLS), '-y', String(AGENT_PANE_ROWS)]
