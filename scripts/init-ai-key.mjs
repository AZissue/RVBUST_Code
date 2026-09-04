import { appendFileSync, readFileSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { resolve } from 'node:path';

const path = resolve('.env');
const contents = readFileSync(path, 'utf8');
const existing = contents.match(/^AI_CONFIG_ENCRYPTION_KEY=(.*)$/m)?.[1]?.trim();
if (existing) {
  if (!/^[a-f\d]{64}$/i.test(existing)) throw new Error('Existing AI_CONFIG_ENCRYPTION_KEY is invalid; refusing to overwrite it.');
  console.log('AI encryption key already configured; unchanged.');
} else if (/^AI_CONFIG_ENCRYPTION_KEY=/m.test(contents)) {
  writeFileSync(path, contents.replace(/^AI_CONFIG_ENCRYPTION_KEY=.*$/m, `AI_CONFIG_ENCRYPTION_KEY=${randomBytes(32).toString('hex')}`), { mode: 0o600 });
  console.log('AI encryption key initialized in backend .env. Restart API and back up this file securely.');
} else {
  appendFileSync(path, `\nAI_CONFIG_ENCRYPTION_KEY=${randomBytes(32).toString('hex')}\n`, { mode: 0o600 });
  console.log('AI encryption key initialized in backend .env. Restart API and back up this file securely.');
}
