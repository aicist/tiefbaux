import { defineConfig, devices } from '@playwright/test'

const useLiveTarget = process.env.E2E_LIVE === '1'

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  fullyParallel: true,
  retries: 0,
  reporter: 'html',
  use: {
    baseURL: useLiveTarget ? 'https://tiefbaux.vercel.app' : 'http://127.0.0.1:4173',
    trace: 'on-first-retry',
  },
  webServer: useLiveTarget
    ? undefined
    : {
        command: 'VITE_API_BASE_URL=https://tiefbaux.vercel.app/backend/api npm run dev -- --host 127.0.0.1 --port 4173',
        url: 'http://127.0.0.1:4173',
        reuseExistingServer: false,
        timeout: 120_000,
      },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
})
