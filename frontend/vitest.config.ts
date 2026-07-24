import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/**/*.test.{ts,tsx}'],
      reporter: ['text', 'json-summary'],
      // Initial all-source baseline: 26.33/19.54/16.08/27.05 percent.
      thresholds: {
        statements: 25,
        branches: 18,
        functions: 15,
        lines: 26,
      },
    },
  },
})
