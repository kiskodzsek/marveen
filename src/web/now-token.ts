// {{NOW}} -> the server's own clock (HH:MM, install zone) at the moment the text is stored.
//
// Retro 2026-11-13 R1 (card 028205dd): agents typed "measured" clock times into inter-agent messages,
// close results and daily-log headings before the time had come: measured read-only on store/claudeclaw.db,
// 7 days before 2026-11-13, about 87 such stamps were 1-15 minutes later than the row's own created_at /
// completed_at ("mérve 15:37 date" stored at 15:35). The PreToolUse time-claim-gate now stops a future
// measured time on that path; this is the other half: the author does not type the time at all. A quoted
// heredoc cannot run `date`, so the token is filled in here, the same principle as the heartbeat header
// stamp (heartbeat-header-stamp.ts): the machine stamps it, the author never types it.
//
// Only the exact token "{{NOW}}" is replaced (no other spelling, no date part): it is a write-time stamp,
// and a text that quotes the token on purpose can write it as "{{ NOW }}".

import { APP_TZ } from '../config.js'

export const NOW_TOKEN = '{{NOW}}'

const HHMM = new Intl.DateTimeFormat('sv-SE', { timeZone: APP_TZ, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })

export function fillNowToken(text: string, now: Date = new Date()): string
export function fillNowToken(text: string | undefined | null, now?: Date): string | undefined | null
export function fillNowToken(text: string | undefined | null, now: Date = new Date()): string | undefined | null {
  if (typeof text !== 'string' || !text.includes(NOW_TOKEN)) return text
  return text.split(NOW_TOKEN).join(HHMM.format(now))
}
