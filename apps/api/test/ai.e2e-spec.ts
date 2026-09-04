import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import dotenv from 'dotenv';
import request, { type Agent } from 'supertest';
import { createCipheriv, createPublicKey, publicEncrypt, randomBytes } from 'node:crypto';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { AppModule } from '../src/app.module.js';
import { PrismaService } from '../src/prisma/prisma.service.js';
import { AIService } from '../src/ai/ai.service.js';
import type { ProviderDto } from '../src/ai/ai.dto.js';

dotenv.config({ path: '../../.env' });
describe('AI gateway with isolated local mock, not live provider credentials', () => {
  let app: INestApplication; let db: PrismaService; let admin: Agent; let employee: Agent; let server: Server;
  let baseUrl: string; let id: string; let otherId: string; let orgId: string; let uid: string; let calls = 0;
  let sealed = '';
  let mode: 'ok' | 'bad-json' | 'hallucination' | 'ids' | 'timeout' | 'redirect' | 'echo-key' | 'status' = 'ok'; let status = 401;
  let lastBody: Record<string, any> = {}; let lastAuth = '';
  const secret = randomBytes(32).toString('hex'); const master = randomBytes(32).toString('hex');
  const savedEnv = { key: process.env.AI_CONFIG_ENCRYPTION_KEY, origins: process.env.AI_ALLOWED_INTERNAL_ORIGINS };
  const rawText = '浙江智享机器人 M2600拍摄3D无点云，张伟负责，紧急';
  const payload = (): ProviderDto => ({ provider: 'deepseek', name: 'Isolated test provider', enabled: true, baseUrl, sealedApiKey: sealed, defaultModel: 'isolated-test-model', temperature: .1, maxTokens: 512, timeout: 1000, isDefault: true, omitTemperature: false, jsonMode: true, tokenParameter: 'max_tokens' });
  const parse = async () => (await admin.post('/api/tickets/quick/parse').send({ rawText }).expect(201)).body;
  beforeAll(async () => {
    if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) throw new Error('Requires isolated quick_ticket_test schema');
    server = createServer((req, res) => {
      calls++; lastAuth = req.headers.authorization ?? '';
      let body = ''; req.on('data', (c) => { body += c }); req.on('end', () => {
        lastBody = body ? JSON.parse(body) : {};
        if (mode === 'timeout') return;
        if (mode === 'redirect') { res.writeHead(302, { Location: 'http://169.254.169.254/' }); res.end(); return; }
        if (mode === 'status') { res.writeHead(status); res.end(JSON.stringify({ error: { message: secret } })); return; }
        res.setHeader('Content-Type', 'application/json');
        if (req.url === '/v1/models') { res.end(JSON.stringify({ data: [{ id: 'isolated-test-model' }] })); return; }
        const extracted = { customerText: '浙江智享机器人', issue: 'M2600拍摄3D无点云', assigneeText: '张伟', priority: 'urgent', deviceText: 'M2600' };
        const content = mode === 'bad-json' ? 'not JSON' : mode === 'echo-key' ? secret : JSON.stringify(mode === 'hallucination' ? { ...extracted, customerText: '虚构客户' } : mode === 'ids' ? { ...extracted, customerId: orgId } : lastBody.messages?.length === 1 ? { ok: true } : extracted);
        res.end(JSON.stringify({ choices: [{ message: { content }, finish_reason: 'stop' }], usage: { prompt_tokens: 123, completion_tokens: 45, total_tokens: 168 } }));
      });
    });
    await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
    baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
    process.env.AI_CONFIG_ENCRYPTION_KEY = master; process.env.AI_ALLOWED_INTERNAL_ORIGINS = new URL(baseUrl).origin;
    const module = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = module.createNestApplication(); app.setGlobalPrefix('api'); app.use(cookieParser()); app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })); await app.init();
    db = app.get(PrismaService); admin = request.agent(app.getHttpServer()); employee = request.agent(app.getHttpServer());
    await admin.post('/api/auth/login').send({ username: 'admin', password: process.env.SEED_ADMIN_PASSWORD }).expect(201);
    await employee.post('/api/auth/login').send({ username: 'employee', password: process.env.SEED_EMPLOYEE_PASSWORD }).expect(201);
    const publicKey = (await admin.get('/api/ai/key-exchange').expect(200)).body.publicKey;
    const aes = randomBytes(32); const iv = randomBytes(12); const cipher = createCipheriv('aes-256-gcm', aes, iv);
    const ciphertext = Buffer.concat([cipher.update(secret), cipher.final(), cipher.getAuthTag()]);
    const wrappedKey = publicEncrypt({ key: createPublicKey({ key: Buffer.from(publicKey, 'base64'), type: 'spki', format: 'der' }), oaepHash: 'sha256' }, aes);
    sealed = ['v1', wrappedKey.toString('base64'), iv.toString('base64'), ciphertext.toString('base64')].join('.');
    if (await db.aIProviderConfig.count()) throw new Error('Test schema has provider configs; refusing to modify them');
    uid = (await db.user.update({ where: { username: 'admin' }, data: { name: '张伟' } })).id;
    orgId = (await db.customerOrganization.upsert({ where: { name: '浙江智享机器人' }, update: {}, create: { name: '浙江智享机器人' } })).id;
  });
  it('uses rules with no provider and does not call network or create entities', async () => {
    const before = await db.ticket.count(); const p = await parse();
    expect(p.parser).toBe('rule'); expect(p.matchedCustomer.id).toBe(orgId); expect(calls).toBe(0); expect(await db.ticket.count()).toBe(before);
  });
  it('restricts all AI configuration endpoints to admins', async () => {
    for (const path of ['providers', 'features', 'usage']) await employee.get(`/api/ai/${path}`).expect(403);
    await employee.post('/api/ai/providers').send(payload()).expect(403);
  });
  it('validates and encrypts key without returning ciphertext or secret', async () => {
    await admin.post('/api/ai/providers').send({ ...payload(), apiKey: secret }).expect(400);
    expect(JSON.stringify(payload())).not.toContain(secret);
    await admin.post('/api/ai/providers').send({ ...payload(), timeout: 0 }).expect(400);
    const response = await admin.post('/api/ai/providers').send(payload()).expect(201); id = response.body.id;
    expect(response.text).not.toContain(secret); expect(response.body.apiKeyEncrypted).toBeUndefined(); expect(response.body.apiKeyMasked).toBe('********');
    const saved = await db.aIProviderConfig.findUniqueOrThrow({ where: { id } }); expect(saved.apiKeyEncrypted).not.toContain(secret);
    expect((await admin.get('/api/ai/providers').expect(200)).body.providers[0].id).toBe(id);
  });
  it('tests connection and models through backend and records usage', async () => {
    const tested = (await admin.post(`/api/ai/providers/${id}/test`).expect(201)).body;
    expect(tested.success).toBe(true); expect(tested.usage.totalTokens).toBe(168); expect(lastAuth).toBe(`Bearer ${secret}`);
    expect((await admin.post(`/api/ai/providers/${id}/models`).expect(201)).body.data).toEqual(['isolated-test-model']);
  });
  it('uses AI extraction, then resolves real allowed entities without writes', async () => {
    const before = await db.ticket.count(); const parsed = await parse();
    expect(parsed.parser).toBe('ai'); expect(parsed.provider).toBe('deepseek'); expect(parsed.matchedCustomer.id).toBe(orgId); expect(parsed.matchedAssignee.id).toBe(uid);
    expect(await db.ticket.count()).toBe(before); expect(JSON.stringify(lastBody)).not.toContain(orgId); expect(JSON.stringify(lastBody)).not.toContain(uid); expect(lastBody.response_format).toEqual({ type: 'json_object' });
  });
  it('switches default to Kimi, supports feature overrides and custom compatible provider', async () => {
    otherId = (await admin.post('/api/ai/providers').send({ ...payload(), provider: 'kimi', name: 'Isolated Kimi adapter' }).expect(201)).body.id;
    expect((await parse()).provider).toBe('kimi'); expect(await db.aIProviderConfig.count({ where: { isDefault: true } })).toBe(1);
    await admin.put('/api/ai/features/quick_ticket_parser').send({ useSystemDefault: false, providerId: id, model: 'override-model', temperature: .2, maxTokens: 256 }).expect(200);
    expect((await parse()).model).toBe('override-model'); expect(lastBody.temperature).toBe(.2); expect(lastBody.max_tokens).toBe(256);
    await admin.put(`/api/ai/providers/${id}`).send({ ...payload(), provider: 'openai-compatible', isDefault: false, sealedApiKey: undefined, omitTemperature: true }).expect(200);
    expect((await parse()).provider).toBe('openai-compatible'); expect(lastBody.temperature).toBeUndefined();
  });
  it('supports OpenAI completion token parameter without model-name assumptions', async () => {
    await admin.put(`/api/ai/providers/${id}`).send({ ...payload(), provider: 'openai', isDefault: false, tokenParameter: 'max_completion_tokens' }).expect(200);
    expect((await parse()).provider).toBe('openai'); expect(lastBody.max_completion_tokens).toBe(256); expect(lastBody.max_tokens).toBeUndefined();
  });
  it.each([[401, 'AUTH'], [403, 'FORBIDDEN'], [404, 'NOT_FOUND'], [429, 'RATE_LIMIT']])('returns sanitized %s error and falls back without retries', async (code, expected) => {
    mode = 'status'; status = Number(code); const before = calls;
    const r = await admin.post(`/api/ai/providers/${id}/test`).expect(201);
    expect(r.body.errorType).toBe(expected); expect(r.text).not.toContain(secret); expect(calls - before).toBe(1);
    expect((await parse()).parser).toBe('rule'); await admin.get('/api/tickets').expect(200); mode = 'ok';
  });
  it.each(['bad-json', 'hallucination', 'ids', 'echo-key'] as const)('rejects %s and falls back', async (value) => { mode = value; expect((await parse()).parser).toBe('rule'); mode = 'ok'; });
  it('does not follow redirects, times out within one shared deadline, limits retry to one', async () => {
    mode = 'redirect'; let before = calls; expect((await parse()).parser).toBe('rule'); expect(calls - before).toBe(1);
    mode = 'timeout'; const start = Date.now(); expect((await parse()).fallbackReason).toContain('超时'); expect(Date.now() - start).toBeLessThan(2500);
    mode = 'status'; status = 503; before = calls; expect((await parse()).parser).toBe('rule'); expect(calls - before).toBe(2); mode = 'ok';
  });
  it('limits concurrent calls per user without blocking normal pages', async () => {
    mode = 'timeout'; const ai = app.get(AIService); const pending = ai.testProvider(id, uid);
    await new Promise((r) => setTimeout(r, 50));
    expect((await ai.testProvider(id, uid)).success).toBe(false); await admin.get('/api/customers').expect(200); await pending; mode = 'ok';
  });
  it('preserves ciphertext on key-blank edits and rejects unsafe destination', async () => {
    const encrypted = (await db.aIProviderConfig.findUniqueOrThrow({ where: { id } })).apiKeyEncrypted;
    await admin.put(`/api/ai/providers/${id}`).send({ ...payload(), sealedApiKey: undefined, isDefault: false }).expect(200);
    expect((await db.aIProviderConfig.findUniqueOrThrow({ where: { id } })).apiKeyEncrypted).toBe(encrypted);
    await admin.put(`/api/ai/providers/${id}`).send({ ...payload(), baseUrl: 'http://169.254.169.254' }).expect(400);
  });
  it('removes/ disables default safely and leaves deleted overrides unresolved', async () => {
    await admin.put(`/api/ai/providers/${otherId}`).send({ ...payload(), enabled: false, isDefault: false }).expect(200);
    expect(await db.aIProviderConfig.count({ where: { isDefault: true } })).toBe(0);
    await admin.delete(`/api/ai/providers/${id}`).expect(200); id = '';
    expect((await parse()).parser).toBe('rule'); expect((await db.aIFeatureConfig.findUniqueOrThrow({ where: { featureKey: 'quick_ticket_parser' } })).providerId).toBeNull();
    await admin.get('/api/dashboard').expect(200);
  });
  it('logs metadata only, not keys, prompts or customer content', async () => {
    const logs = await admin.get('/api/ai/usage').expect(200);
    expect(logs.text).not.toContain(secret); expect(logs.text).not.toContain(master); expect(logs.text).not.toContain(rawText);
    expect(logs.body.some((r: { errorType: string }) => r.errorType === 'TIMEOUT')).toBe(true);
    expect(logs.body.some((r: { errorType: string; totalTokens: number }) => r.errorType === 'INVALID_OUTPUT' && r.totalTokens === 168)).toBe(true);
  });
  afterAll(async () => {
    if (db) { if (id) await db.aIProviderConfig.deleteMany({ where: { id } }); if (otherId) await db.aIProviderConfig.deleteMany({ where: { id: otherId } }); await db.aIFeatureConfig.deleteMany({ where: { featureKey: 'quick_ticket_parser' } }); }
    await app?.close(); server?.closeAllConnections(); await new Promise<void>((resolve) => server ? server.close(() => resolve()) : resolve());
    if (savedEnv.key === undefined) delete process.env.AI_CONFIG_ENCRYPTION_KEY; else process.env.AI_CONFIG_ENCRYPTION_KEY = savedEnv.key;
    if (savedEnv.origins === undefined) delete process.env.AI_ALLOWED_INTERNAL_ORIGINS; else process.env.AI_ALLOWED_INTERNAL_ORIGINS = savedEnv.origins;
  });
});
