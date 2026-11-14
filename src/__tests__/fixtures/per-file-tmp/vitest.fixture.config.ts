// A nested vitest run for per-file-tmp.test.ts (card 400faadf): the REAL globalSetup and the REAL per-file setup,
// with fixture files the main run never collects (*.fixture.ts is not a test pattern).
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const here = (p: string): string => fileURLToPath(new URL(p, import.meta.url))

export default defineConfig({
  test: {
    include: ['*.fixture.ts'],
    globalSetup: [here('../../setup/disk-and-tmp-root.ts')],
    setupFiles: [here('../../setup/per-file-tmp.ts')],
  },
})
