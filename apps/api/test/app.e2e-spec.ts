import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import dotenv from 'dotenv';
import request, { type Agent } from 'supertest';
import type { App } from 'supertest/types';
import { AppModule } from '../src/app.module.js';

dotenv.config({ path: '../../.env' });

describe('Phase 1 domain flows (e2e)', () => {
  let app: INestApplication<App>;
  let admin: Agent;
  let employee: Agent;
  let customer: Agent;
  const createdLogIds: string[] = [];
  let createdWorkItemId = '';

  beforeAll(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = moduleFixture.createNestApplication();
    app.setGlobalPrefix('api');
    app.use(cookieParser());
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }));
    await app.init();
    admin = request.agent(app.getHttpServer());
    employee = request.agent(app.getHttpServer());
    customer = request.agent(app.getHttpServer());
    await admin.post('/api/auth/login').send({ username: 'admin', password: process.env.SEED_ADMIN_PASSWORD }).expect(201);
    await employee.post('/api/auth/login').send({ username: 'employee', password: process.env.SEED_EMPLOYEE_PASSWORD }).expect(201);
    await customer.post('/api/auth/login').send({ username: 'customer', password: process.env.SEED_CUSTOMER_PASSWORD }).expect(201);
  });

  it('rejects unauthenticated access', () => request(app.getHttpServer()).get('/api/work-items').expect(401));

  it('enforces role boundaries for internal and admin modules', async () => {
    await employee.get('/api/users').expect(403);
    await customer.get('/api/work-items').expect(403);
    await admin.get('/api/users').expect(200);
  });

  it('returns a separate analytics dataset built from real records', async () => {
    const report = await admin.get('/api/dashboard/reports').expect(200);
    expect(report.body.daily).toHaveLength(7);
    expect(report.body.summary).toEqual(expect.objectContaining({ weeklyWorklogs: expect.any(Number), completionRate: expect.any(Number) }));
  });

  it('creates and updates a work item independently from tickets', async () => {
    const workTypes = await admin.get('/api/work-types').expect(200);
    const type = workTypes.body.find((item: { code: string }) => item.code === 'documentation');
    const created = await admin.post('/api/work-items').send({ title: 'E2E 文档整理事项', description: '自动测试创建', workTypeId: type.id, priority: 'HIGH', progress: 20, tags: ['e2e'] }).expect(201);
    createdWorkItemId = created.body.id;
    expect(created.body.status).toBe('TODO');
    expect(created.body.workType.code).toBe('documentation');
    expect((await admin.get(`/api/work-items/${createdWorkItemId}`).expect(200)).body.progress).toBe(20);
    await admin.patch(`/api/work-items/${createdWorkItemId}`).send({ status: 'IN_PROGRESS', progress: 60, dueDate: '2030-09-06' }).expect(200);
    const persisted = (await admin.get(`/api/work-items/${createdWorkItemId}`).expect(200)).body;
    expect(persisted.progress).toBe(60);
    expect(persisted.dueDate).toContain('2030-09-06');
    const hundred = await admin.patch(`/api/work-items/${createdWorkItemId}`).send({ progress: 100 }).expect(200);
    expect(hundred.body.progress).toBe(100);
    expect(hundred.body.status).toBe('IN_PROGRESS');
    expect(hundred.body.completedAt).toBeNull();
    const completed = await admin.patch(`/api/work-items/${createdWorkItemId}`).send({ status: 'COMPLETED' }).expect(200);
    expect(completed.body.progress).toBe(100);
    expect(completed.body.completedAt).toBeTruthy();
  });

  it('allows a confirmed work log with no ticket or work item', async () => {
    const types = await admin.get('/api/work-types').expect(200);
    const type = types.body.find((item: { code: string }) => item.code === 'internal-support');
    const created = await admin.post('/api/worklogs').send({ occurredAt: new Date().toISOString(), workTypeId: type.id, summary: '独立工作事实记录', durationMinutes: 20 }).expect(201);
    createdLogIds.push(created.body.id);
    expect(created.body.status).toBe('CONFIRMED');
    expect(created.body.ticket).toBeNull();
    expect(created.body.workItem).toBeNull();
  });

  it('links a work log to a work item without turning it into a ticket', async () => {
    const types = await admin.get('/api/work-types').expect(200);
    const type = types.body.find((item: { code: string }) => item.code === 'documentation');
    const created = await admin.post('/api/worklogs').send({ occurredAt: new Date().toISOString(), workTypeId: type.id, workItemId: createdWorkItemId, summary: '完成文档目录整理' }).expect(201);
    createdLogIds.push(created.body.id);
    expect(created.body.workItem.id).toBe(createdWorkItemId);
    expect(created.body.ticket).toBeNull();
  });

  it('creates multiple drafts from one raw text and confirms the batch', async () => {
    const types = await admin.get('/api/work-types').expect(200);
    const type = types.body.find((item: { code: string }) => item.code === 'customer-support');
    const created = await admin.post('/api/worklogs/drafts').send({ rawText: '完成SDK教程；排查M2600无点云。', occurredAt: new Date().toISOString(), workTypeId: type.id, summaries: ['完成SDK教程', '排查M2600无点云'] }).expect(201);
    expect(created.body).toHaveLength(2);
    expect(new Set(created.body.map((item: { aiExtractionId: string }) => item.aiExtractionId)).size).toBe(1);
    expect(created.body.every((item: { status: string }) => item.status === 'DRAFT')).toBe(true);
    created.body.forEach((item: { id: string }) => createdLogIds.push(item.id));
    const confirmed = await admin.post(`/api/worklogs/drafts/${created.body[0].aiExtractionId}/confirm`).expect(201);
    expect(confirmed.body.every((item: { status: string }) => item.status === 'CONFIRMED')).toBe(true);
  });

  it('invalidates the current session on logout', async () => {
    const isolated = request.agent(app.getHttpServer());
    await isolated.post('/api/auth/login').send({ username: 'support', password: process.env.SEED_SUPPORT_PASSWORD }).expect(201);
    await isolated.post('/api/auth/logout').expect(201);
    await isolated.get('/api/auth/me').expect(401);
  });

  afterAll(async () => {
    for (const id of createdLogIds) await admin.delete(`/api/worklogs/${id}`);
    if (createdWorkItemId) await admin.delete(`/api/work-items/${createdWorkItemId}`);
    await app.close();
  });
});
