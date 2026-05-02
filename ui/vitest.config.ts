import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.{ts,tsx}'],
    setupFiles: ['./tests/setup.ts'],
    coverage: {
      provider: 'v8',
      // Generated files and pure type re-exports: no runtime behaviour to test.
      exclude: [
        '**/*.d.ts',
        'src/types/generated-enums.ts',
        'src/types/**',
        '**/__mocks__/**',
      ],
      thresholds: { lines: 37, branches: 31 },
    },
  },
})
