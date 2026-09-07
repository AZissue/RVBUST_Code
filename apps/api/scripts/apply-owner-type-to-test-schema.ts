// 一次性脚本：把 device_owner_type 迁移的 SQL 应用到隔离的 quick_ticket_test schema。
// 仅限测试库使用；正式库已由 prisma migrate 应用。
import { readFileSync } from 'node:fs';
import dotenv from 'dotenv';
import { PrismaClient } from '@prisma/client';

dotenv.config({ path: '../../.env' });
const base = process.env.DATABASE_URL ?? 'postgresql://tech_support:tech_support@localhost:5432/tech_support_v2';
const [url] = base.split('?');
const testUrl = `${url}?schema=quick_ticket_test`;
if (!testUrl.includes('schema=quick_ticket_test')) throw new Error('refusing to touch non-test schema');

const sql = readFileSync(new URL('../prisma/migrations/202609071300_device_owner_type/migration.sql', import.meta.url), 'utf8');
const prisma = new PrismaClient({ datasources: { db: { url: testUrl } } });
try {
  for (const statement of sql.split(';').map((chunk) => chunk.trim()).filter(Boolean)) {
    await prisma.$executeRawUnsafe(statement);
  }
  console.log('applied device_owner_type migration SQL to quick_ticket_test');
} catch (error) {
  // 重复执行时忽略已存在的对象
  console.log('skipped:', (error as Error).message);
} finally {
  await prisma.$disconnect();
}
