import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${process.env.WEB_PORT ?? 5173}`,
    trace: 'retain-on-failure',
    channel: process.env.PW_CHANNEL, // 设置 PW_CHANNEL=chrome 可使用系统 Chrome 跑测试，无需下载浏览器
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    { command: 'npm run start:dev -w apps/api', url: `http://127.0.0.1:${process.env.API_PORT ?? 3001}/api/health`, reuseExistingServer: true, timeout: 120_000 },
    { command: 'npm run dev -w apps/web', url: `http://127.0.0.1:${process.env.WEB_PORT ?? 5173}`, reuseExistingServer: true, timeout: 120_000 },
  ],
})
