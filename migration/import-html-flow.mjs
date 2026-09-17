import fs from 'node:fs';
import { createHash } from 'node:crypto';
import { PrismaClient } from '@prisma/client';

const input = process.argv[2];
if (!input) throw new Error('Usage: node migration/import-html-flow.mjs <original-html> [--apply-preview]');
const source = fs.readFileSync(input, 'utf8');
const hash = createHash('sha256').update(source).digest('hex');
const lines = source.split(/\r?\n/);
function embedded(key) {
  const prefix = `if(!localStorage.getItem(${key}))save(${key},`;
  const line = lines.find((value) => value.startsWith(prefix));
  if (!line || !line.endsWith(');')) throw new Error(`Embedded ${key} data not found`);
  return JSON.parse(line.slice(prefix.length, -2));
}
const records = embedded('DB_KEY');
const devices = embedded('DEV_KEY');
const followups = [];
for (const record of records) {
  for (const [sequence, f] of (record.followUps ?? []).entries()) {
    followups.push({
      id: String(f.id || `${record.id}-FU-${sequence}`),
      recordId: String(record.id),
      sequence,
      person: f.person || null,
      date: f.date || null,
      content: String(f.text || ''),
      source: f.source || null,
    });
  }
  delete record.followUps;
}
const summary = { sourceHash: hash, records: records.length, repairs: records.filter((r) => r.type === 'repair').length, loans: records.filter((r) => r.type === 'loan').length, devices: devices.length, followups: followups.length, imageRecords: records.filter((r) => Object.keys(r.photos || {}).length).length, agreements: records.filter((r) => r.agreement).length };
console.log(JSON.stringify(summary, null, 2));
if (!process.argv.includes('--apply-preview')) process.exit(0);
const url = new URL(process.env.DATABASE_URL || '');
if (url.hostname !== '127.0.0.1' || url.port !== '5544' || url.pathname !== '/flow_github_21b4129') {
  throw new Error('Import is restricted to the isolated flow_github_21b4129 preview database');
}
const prisma = new PrismaClient();
try {
  await prisma.$transaction(async (tx) => {
    if (await tx.htmlFlowState.count({ where: { id: 'main' } })) throw new Error('Preview already contains flow data; import aborted');
    await tx.htmlFlowState.create({ data: { id: 'main', revision: 0, data: { records, devices, recycle: { records: [], devices: [] }, settings: {} } } });
    if (followups.length) await tx.htmlFlowFollowup.createMany({ data: followups });
  }, { timeout: 30000 });
  console.log('Import completed into isolated preview database');
} finally {
  await prisma.$disconnect();
}
