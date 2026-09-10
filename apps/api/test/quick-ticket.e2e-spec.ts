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
    const dto = { category: 'HARDWARE_FAILURE', organizationId: orgId, deviceId, assigneeId: supportId, cameraModel: 'M2600', title: 'M2600连接超时', description: 'M2600连接超时', rawText: '浙江智享 M2600连接超时 李四 紧急', priority: 'URGENT', requestKey: randomUUID() };
    const ticket = (await admin.post('/api/tickets').send(dto).expect(201)).body; ticketId = ticket.id;
    expect((await admin.post('/api/tickets').send(dto).expect(201)).body.id).toBe(ticketId);
    expect((await admin.get('/api/tickets?mine=1').expect(200)).body.items.some((t: { id: string }) => t.id === ticketId)).toBe(false);
    expect((await support.get('/api/tickets?mine=1').expect(200)).body.items.some((t: { id: string }) => t.id === ticketId)).toBe(true);
    const stored = (await admin.get(`/api/tickets/${ticketId}`).expect(200)).body;
    expect(stored.rawText).toBe(dto.rawText); expect(stored.device.id).toBe(deviceId);
  });
  it('parses backdate expressions and backdates number/createdAt on create', async () => {
    const parsed = (await admin.post('/api/tickets/quick/parse').send({ rawText: '本周一 浙江智享 M2600连接超时 李四' }).expect(201)).body;
    expect(parsed.occurredAt).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(parsed.issue).not.toContain('本周一');
    // 明确指定历史日期：createdAt 与编号都按该日期
    const backdated = (await admin.post('/api/tickets').send({ category: 'HARDWARE_FAILURE', organizationId: orgId, assigneeId: supportId, title: '补录历史连接超时', description: '补录历史连接超时', occurredAt: '2026-09-07', requestKey: randomUUID() }).expect(201)).body;
    expect(backdated.number).toMatch(/^RVC-260907-\d{3}$/);
    const created = new Date(backdated.createdAt);
    expect(`${created.getFullYear()}-${String(created.getMonth() + 1).padStart(2, '0')}-${String(created.getDate()).padStart(2, '0')}`).toBe('2026-09-07');
    // 编号顺序仍按当日递增
    const second = (await admin.post('/api/tickets').send({ category: 'HARDWARE_FAILURE', organizationId: orgId, title: '补录历史连接超时2', description: '补录历史连接超时2', occurredAt: '2026-09-07', requestKey: randomUUID() }).expect(201)).body;
    expect(Number(second.number.slice(-3))).toBe(Number(backdated.number.slice(-3)) + 1);
    await db.ticket.delete({ where: { id: backdated.id } });
    await db.ticket.delete({ where: { id: second.id } });
  });
  it('creates tickets with explicit initial status and resolvedAt for RESOLVED', async () => {
    const parsed = (await admin.post('/api/tickets/quick/parse').send({ rawText: '0907 浙江智享 M2600连接超时 已解决' }).expect(201)).body;
    expect(parsed.status).toBe('RESOLVED');
    expect(parsed.occurredAt).toBeTruthy();
    expect(parsed.issue).not.toContain('已解决');
    const resolved = (await admin.post('/api/tickets').send({ category: 'HARDWARE_FAILURE', organizationId: orgId, title: '补录已解决问题', description: '补录已解决问题', occurredAt: parsed.occurredAt, status: 'RESOLVED', requestKey: randomUUID() }).expect(201)).body;
    expect(resolved.status).toBe('RESOLVED');
    expect(resolved.resolvedAt).toBeTruthy();
    const waiting = (await admin.post('/api/tickets').send({ category: 'HARDWARE_FAILURE', organizationId: orgId, title: '补录等待客户', description: '补录等待客户', status: 'WAITING_CUSTOMER', requestKey: randomUUID() }).expect(201)).body;
    expect(waiting.status).toBe('WAITING_CUSTOMER');
    expect(waiting.resolvedAt).toBeNull();
    await db.ticket.delete({ where: { id: resolved.id } });
    await db.ticket.delete({ where: { id: waiting.id } });
  });
  it('paginates ticket list 20 per page with server-side search and status counts', async () => {
    // 串行创建避免并发编号冲突
    const ids: string[] = [];
    for (let i = 0; i < 25; i++) ids.push((await admin.post('/api/tickets').send({ category: 'OTHER', organizationId: orgId, title: `分页验证工单${i}号`, description: `分页验证工单${i}号描述`, requestKey: randomUUID() }).expect(201)).body.id as string);
    const page1 = (await admin.get('/api/tickets').expect(200)).body;
    expect(page1.items.length).toBe(20);
    expect(page1.pageSize).toBe(20);
    expect(page1.total).toBeGreaterThanOrEqual(25);
    expect(Object.values(page1.byStatus).reduce((sum: number, count) => sum + (count as number), 0)).toBe(page1.total);
    const page2 = (await admin.get('/api/tickets?page=2').expect(200)).body;
    expect(page2.page).toBe(2);
    expect(page2.items.length).toBe(Math.min(20, page2.total - 20));
    // 服务端搜索命中编号/标题
    const found = (await admin.get(`/api/tickets?search=${encodeURIComponent('分页验证工单7号')}`).expect(200)).body;
    expect(found.items.some((t: { id: string }) => ids.includes(t.id))).toBe(true);
    // 状态过滤 + 非法状态
    const pending = (await admin.get('/api/tickets?status=PENDING,CLOSED').expect(200)).body;
    expect(pending.items.every((t: { status: string }) => ['PENDING', 'CLOSED'].includes(t.status))).toBe(true);
    await admin.get('/api/tickets?status=NOPE').expect(400);
    // all=1 保持数组形态（引用数据下拉）
    expect(Array.isArray((await admin.get('/api/tickets?all=1').expect(200)).body)).toBe(true);
    await db.ticket.deleteMany({ where: { id: { in: ids } } });
  });
  it('detects similar same-customer tickets without leaking cross-customer tickets', async () => {
    const dto = { organizationId: orgId, issue: 'M2600连接不上', cameraModel: 'M2600' };
    const matches = (await admin.post('/api/tickets/quick/similar').send(dto).expect(201)).body;
    expect(matches.find((t: { id: string }) => t.id === ticketId).similarity).toBeGreaterThan(80);
    // 内部角色可见全部工单，employee 与 admin 看到的相似工单一致
    const employeeMatches = (await employee.post('/api/tickets/quick/similar').send(dto).expect(201)).body;
    expect(employeeMatches.find((t: { id: string }) => t.id === ticketId).similarity).toBeGreaterThan(80);
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
    expect((await support.get('/api/tickets?mine=1').expect(200)).body.items.some((t: { id: string }) => t.id === ticketId)).toBe(false);
    expect((await admin.get('/api/tickets?mine=1').expect(200)).body.items.some((t: { id: string }) => t.id === ticketId)).toBe(true);
  });
  it('updates personal and dashboard status from the same ticket', async () => {
    await admin.post(`/api/tickets/${ticketId}/status`).send({ status: 'IN_PROGRESS' }).expect(201);
    const dashboard = (await admin.get('/api/dashboard').expect(200)).body;
    const mine = (await admin.get('/api/tickets?mine=1').expect(200)).body.items;
    expect(dashboard.ticketCounts.inProgress).toBe(mine.filter((t: { status: string }) => t.status === 'IN_PROGRESS').length);
    // 工作台汇总包含借测/返修计数与需要关注分组
    expect(typeof dashboard.overdueLoanCount).toBe('number');
    expect(typeof dashboard.repairingCount).toBe('number');
    expect(Array.isArray(dashboard.alerts.stale)).toBe(true);
    expect(Array.isArray(dashboard.alerts.overduePlan)).toBe(true);
    expect(Array.isArray(dashboard.alerts.waitingTimeout)).toBe(true);
    // 计划逾期未兑现的未解决工单进入 alerts.overduePlan
    const overdue = (await admin.post('/api/tickets').send({ category: 'OTHER', organizationId: orgId, assigneeId: adminId, title: '逾期计划验证', description: '逾期计划验证', plannedAt: new Date(Date.now() - 86400000).toISOString() }).expect(201)).body;
    const dash2 = (await admin.get('/api/dashboard').expect(200)).body;
    expect(dash2.alerts.overduePlan.some((t: { id: string }) => t.id === overdue.id)).toBe(true);
    expect(dash2.alerts.stale.some((t: { id: string }) => t.id === overdue.id)).toBe(false);
    await db.ticket.deleteMany({ where: { id: overdue.id } });
    await admin.post(`/api/tickets/${ticketId}/status`).send({ status: 'WAITING_RND' }).expect(201);
    await admin.post(`/api/tickets/${ticketId}/status`).send({ status: 'RESOLVED' }).expect(201);
    expect((await admin.get('/api/dashboard').expect(200)).body.ticketCounts.todayCompleted).toBeGreaterThan(0);
  });
  it('rejects missing customer, invalid assignee, cross-customer device and blank descriptions', async () => {
    const dto = { category: 'OTHER', organizationId: orgId, title: 'M2600无点云', description: 'M2600无点云' };
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
    await admin.delete(`/api/tickets/${converted.id}`).expect(200);
    await admin.delete(`/api/tickets/${converted.id}/purge`).expect(409);
    await admin.post(`/api/tickets/${converted.id}/restore`).expect(201);
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
