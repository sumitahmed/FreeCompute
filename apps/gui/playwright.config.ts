import { defineConfig } from '@playwright/test'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

process.env.FC_GUI_E2E_INFO ||= join(tmpdir(), `fc-gui-e2e-${process.pid}.json`)
export default defineConfig({
  testDir: './e2e', timeout: 45000, fullyParallel: false, workers: 1, retries: 0,
  use: { baseURL: 'http://127.0.0.1:8749', browserName: 'chromium', viewport: { width: 1440, height: 960 }, screenshot: 'only-on-failure', trace: 'off' },
  reporter: [['list']],
  webServer: { command: `python tests/gui_server.py --info "${process.env.FC_GUI_E2E_INFO}" --port 8749`,
    cwd: '../..', url: 'http://127.0.0.1:8749/healthz', reuseExistingServer: false, timeout: 30000,
    gracefulShutdown: { signal: 'SIGINT', timeout: 7000 } },
})
