import { config as loadEnv } from 'dotenv';
import { defineConfig } from 'vitest/config';
import tsconfigPaths from 'vite-tsconfig-paths';

// e2e 一律运行在隔离的 quick_ticket_test schema，避免污染正式数据。
// 若外部环境已显式给出带 schema 的测试库地址则沿用，否则基于 .env 的 DATABASE_URL 改写。
loadEnv({ path: ['.env', '../../.env'] });
if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) {
  const base = process.env.DATABASE_URL ?? 'postgresql://tech_support:tech_support@localhost:5432/tech_support_v2';
  const [url] = base.split('?');
  process.env.DATABASE_URL = `${url}?schema=quick_ticket_test`;
}

export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    fileParallelism: false,
    globals: true,
    root: './',
    include: ['**/*.e2e-spec.ts'],
  },
});
