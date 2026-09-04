import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import dotenv from 'dotenv';
import request, { type Agent } from 'supertest';
import { randomUUID } from 'node:crypto';
import { AppModule } from '../src/app.module.js';
import { PrismaService } from '../src/prisma/prisma.service.js';

dotenv.config({ path: '../../.env' });
describe('Quick tickets and single-source personal work', () => {
  let app: INestApplication; let db: PrismaService; let admin: Agent; let support: Agent; let employee: Agent; let customer: Agent;
  let adminId: string; let supportId: string; let orgId: string; let org2: string; let deviceId: string; let ticketId: string; let legacyId: string;
  beforeAll(async () => {
    if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) throw new Error('Requires isolated quick_ticket_test schema');
    const module = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = module.createNestApplication(); app.setGlobalPrefix('api'); app.use(cookieParser()); app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })); await app.init();
    db = app.get(PrismaService);
    admin = request.agent(app.getHttpServer()); support = request.agent(app.getHttpServer()); employee = request.agent(app.getHttpServer()); customer = request.agent(app.getHttpServer());
    for (const [agent, username, password] of [[admin, 'admin', process.env.SEED_ADMIN_PASSWORD], [support, 'support', process.env.SEED_SUPPORT_PASSWORD], [employee, 'employee', process.env.SEED_EMPLOYEE_PASSWORD], [customer, 'customer', process.env.SEED_CUSTOMER_PASSWORD]] as const) await agent.post('/api/auth/login').send({ username, password }).expect(201);
    adminId = (await db.user.update({ where: { username: 'admin' }, data: { name: '张伟' } })).id;
    supportId = (await db.user.update({ where: { username: 'support' }, data: { name: '李四' } })).id;
    orgId = (await db.customerOrganization.upsert({ where: { name: '浙江智享机器人' }, update: {}, create: { name: '浙江智享机器人' } })).id;
    org2 = (await db.customerOrganization.upsert({ where: { name: '工布公司' }, update: {}, create: { name: '工布公司' } })).id;
    deviceId = (await db.device.create({ data: { organizationId: orgId, name: 'M2600', cameraModel: 'M2600', serialNumber: randomUUID() } })).id;
  });
  it.each([
    ['浙江智享机器人 M2600拍摄3D无点云 张伟 紧急', 'URGENT', true],
    ['浙江智享 M2600连接不上 张伟 高优先级', 'HIGH', true],
    ['工布 G52000 2D正常3D无点云 李四 普通', 'MEDIUM', true],
    ['浙江智享机器人 M2600拍摄超时', 'MEDIUM', true],
    ['M2600无点云 张伟 紧急', 'URGENT', false],
  ])('parses against real database without creating records: %s', async (rawText, priority, matched) => {
    const before = await db.ticket.count();
    const parsed = (await admin.post('/api/tickets/quick/parse').send({ rawText }).expect(201)).body;
    expect(Boolean(parsed.matchedCustomer)).toBe(matched); expect(parsed.priority).toBe(priority);
    expect(await db.ticket.count()).toBe(before);
  });
  it('creates a real ticket exactly once and scopes my work by assignee only', async () => {
    const dto = { source: 'AFTER_SALES_INCIDENT', category: '网络连接', organizationId: orgId, deviceId, assigneeId: supportId, cameraModel: 'M2600', title: 'M2600连接超时', description: 'M2600连接超时', rawText: '浙江智享 M2600连接超时 李四 紧急', priority: 'URGENT', requestKey: randomUUID() };
    const ticket = (await admin.post('/api/tickets').send(dto).expect(201)).body; ticketId = ticket.id;
    expect((await admin.post('/api/tickets').send(dto).expect(201)).body.id).toBe(ticketId);
    expect((await admin.get('/api/tickets?mine=1').expect(200)).body.some((t: { id: string }) => t.id === ticketId)).toBe(false);
    expect((await support.get('/api/tickets?mine=1').expect(200)).body.some((t: { id: string }) => t.id === ticketId)).toBe(true);
    const stored = (await admin.get(`/api/tickets/${ticketId}`).expect(200)).body;
    expect(stored.rawText).toBe(dto.rawText); expect(stored.device.id).toBe(deviceId);
  });
  it('detects similar same-customer tickets without leaking inaccessible tickets', async () => {
    const dto = { organizationId: orgId, issue: 'M2600连接不上', cameraModel: 'M2600' };
    const matches = (await admin.post('/api/tickets/quick/similar').send(dto).expect(201)).body;
    expect(matches.find((t: { id: string }) => t.id === ticketId).similarity).toBeGreaterThan(80);
    expect((await employee.post('/api/tickets/quick/similar').send(dto).expect(201)).body).toHaveLength(0);
    expect((await admin.post('/api/tickets/quick/similar').send({ ...dto, organizationId: org2 }).expect(201)).body).toHaveLength(0);
    await customer.post('/api/tickets/quick/parse').send({ rawText: '浙江智享 M2600无点云' }).expect(403);
  });
  it('updates existing ticket with optimistic concurrency, not overwriting problem or status', async () => {
    const before = (await admin.get(`/api/tickets/${ticketId}`).expect(200)).body;
    const dto = { organizationId: orgId, assigneeId: adminId, priority: 'HIGH', issue: '调整巨帧后仍然连接超时', rawText: '浙江智享 调整巨帧后仍然连接超时 张伟 高优先级', expectedUpdatedAt: before.updatedAt };
    await admin.post(`/api/tickets/${ticketId}/quick-update`).send(dto).expect(201);
    await admin.post(`/api/tickets/${ticketId}/quick-update`).send(dto).expect(409);
    const updated = (await admin.get(`/api/tickets/${ticketId}`).expect(200)).body;
    expect(updated.description).toBe(before.description); expect(updated.status).toBe(before.status);
    expect(updated.events.at(-1).content).toBe(dto.issue);
    expect((await support.get('/api/tickets?mine=1').expect(200)).body.some((t: { id: string }) => t.id === ticketId)).toBe(false);
    expect((await admin.get('/api/tickets?mine=1').expect(200)).body.some((t: { id: string }) => t.id === ticketId)).toBe(true);
  });
  it('updates personal and dashboard status from the same ticket', async () => {
    await admin.post(`/api/tickets/${ticketId}/status`).send({ status: 'IN_PROGRESS' }).expect(201);
    const dashboard = (await admin.get('/api/dashboard').expect(200)).body;
    const mine = (await admin.get('/api/tickets?mine=1').expect(200)).body;
    expect(dashboard.ticketCounts.inProgress).toBe(mine.filter((t: { status: string }) => t.status === 'IN_PROGRESS').length);
    await admin.post(`/api/tickets/${ticketId}/status`).send({ status: 'WAITING_RND' }).expect(201);
    await admin.post(`/api/tickets/${ticketId}/status`).send({ status: 'RESOLVED' }).expect(201);
    expect((await admin.get('/api/dashboard').expect(200)).body.ticketCounts.todayCompleted).toBeGreaterThan(0);
  });
  it('rejects missing customer, invalid assignee, cross-customer device and blank descriptions', async () => {
    const dto = { source: 'OTHER', category: '测试', organizationId: orgId, title: 'M2600无点云', description: 'M2600无点云' };
    await admin.post('/api/tickets').send({ ...dto, organizationId: undefined }).expect(400);
    await admin.post('/api/tickets').send({ ...dto, assigneeId: randomUUID() }).expect(400);
    await admin.post('/api/tickets').send({ ...dto, organizationId: org2, deviceId }).expect(400);
    await admin.post('/api/tickets').send({ ...dto, description: '   ' }).expect(400);
  });
  it('converts a historical item once and preserves original facts', async () => {
    const type = await db.workType.findFirstOrThrow();
    const item = await db.workItem.create({ data: { title: '历史客户测试问题', description: '历史事实', ownerId: adminId, workTypeId: type.id, progress: 60, status: 'IN_PROGRESS' } }); legacyId = item.id;
    const log = await db.worklog.create({ data: { authorId: adminId, workTypeId: type.id, workItemId: item.id, occurredAt: new Date(), summary: '实际测试' } });
    const dto = { organizationId: orgId };
    const converted = (await admin.post(`/api/tickets/from-work-item/${item.id}`).send(dto).expect(201)).body;
    expect((await admin.post(`/api/tickets/from-work-item/${item.id}`).send(dto).expect(201)).body.id).toBe(converted.id);
    expect((await db.workItem.findUniqueOrThrow({ where: { id: item.id } })).progress).toBe(60);
    expect((await db.worklog.findUniqueOrThrow({ where: { id: log.id } })).ticketId).toBe(converted.id);
    await admin.patch(`/api/work-items/${item.id}`).send({ title: '不要修改' }).expect(409);
    await admin.delete(`/api/tickets/${converted.id}`).expect(409);
    await admin.post('/api/worklogs').send({ workTypeId: type.id, workItemId: item.id, occurredAt: new Date().toISOString(), summary: '转换后的新记录' }).expect(403);
    await db.worklog.delete({ where: { id: log.id } });
    await db.workItem.delete({ where: { id: legacyId } }); legacyId = '';
    await db.ticket.delete({ where: { id: converted.id } });
  });
  afterAll(async () => {
    if (ticketId) await db.ticket.delete({ where: { id: ticketId } });
    if (deviceId) await db.device.delete({ where: { id: deviceId } });
    await app?.close();
  });
});
