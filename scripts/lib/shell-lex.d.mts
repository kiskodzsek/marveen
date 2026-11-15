// Types for scripts/lib/shell-lex.mjs (card fae0712e), so src/ can import the shared shell lexer.
export interface ShellHeredoc { op: number; opEnd: number; delim: string; quoted: boolean; stripTabs: boolean; bodyStart: number; bodyEnd: number; end: number }
export interface ShellSubst { kind: string; start: number; end: number; inner: [number, number] }
export interface ShellSegment { start: number; end: number; depth: number; frame: string; frameAt: number }
export interface ShellLex { cls: string; problems: string[]; heredocs: ShellHeredoc[]; substs: ShellSubst[]; segments: ShellSegment[] }
export interface ShellWord { text: string; start: number; end: number; quoted: boolean; expands: boolean }
export function lex(text: string): ShellLex
export function words(text: string, lx: ShellLex, seg: ShellSegment): ShellWord[]
export function ansiC(raw: string): string
