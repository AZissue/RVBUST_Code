import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import dotenv from 'dotenv';
import request, { type Agent } from 'supertest';
import { randomUUID } from 'node:crypto';
import { AppModule } from '../src/app.module.js';
import { PrismaService } from '../src/prisma/prisma.service.js';

dotenv.config({ path: '../../.env' });

describe('Redesign v1 flows (e2e)', () => {
  let app: INestApplication; let db: PrismaService;
  let admin: Agent; let support: Agent; let employee: Agent;
  let adminId: string; let employeeId: string; let supportId: string; let orgId: string;
  const suffix = randomUUID().slice(0, 8);
  const regUsername = `reg_${suffix}`;
  const regPassword = 'register-pass-1';

  beforeAll(async () => {
    if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) throw new Error('Requires isolated quick_ticket_test schema');
    const module = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = module.createNestApplication(); app.setGlobalPrefix('api'); app.use(cookieParser());
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })); await app.init();
    db = app.get(PrismaService);
    admin = request.agent(app.getHttpServer()); support = request.agent(app.getHttpServer()); employee = request.agent(app.getHttpServer());
    await admin.post('/api/auth/login').send({ username: 'admin', password: process.env.SEED_ADMIN_PASSWORD }).expect(201);
    await support.post('/api/auth/login').send({ username: 'support', password: process.env.SEED_SUPPORT_PASSWORD }).expect(201);
    await employee.post('/api/auth/login').send({ username: 'employee', password: process.env.SEED_EMPLOYEE_PASSWORD }).expect(201);
    adminId = (await db.user.findUniqueOrThrow({ where: { username: 'admin' } })).id;
    employeeId = (await db.user.findUniqueOrThrow({ where: { username: 'employee' } })).id;
    supportId = (await db.user.findUniqueOrThrow({ where: { username: 'support' } })).id;
    orgId = (await db.customerOrganization.upsert({ where: { name: `借测客户-${suffix}` }, update: {}, create: { name: `借测客户-${suffix}` } })).id;
  });

  afterAll(async () => { await app?.close(); });

  it('registers a PENDING user, blocks login until admin approval, then allows login', async () => {
    const registered = await request(app.getHttpServer()).post('/api/auth/register').send({ username: regUsername, password: regPassword, name: '注册测试', department: '售后部' }).expect(201);
    expect(registered.body.message).toContain('审批');
    const pending = await db.user.findUniqueOrThrow({ where: { username: regUsername }, include: { role: true } });
    expect(pending.status).toBe('PENDING');
    expect(pending.role).toMatchObject({ name: 'employee' });
    // 重复用户名返回同样的模糊提示（防枚举）
    const dup = await request(app.getHttpServer()).post('/api/auth/register').send({ username: regUsername, password: regPassword, name: '注册测试' }).expect(201);
    expect(dup.body.message).toBe(registered.body.message);
    // PENDING 登录被拒
    const rejected = await request(app.getHttpServer()).post('/api/auth/login').send({ username: regUsername, password: regPassword }).expect(401);
    expect(rejected.body.message).toBe('账号等待管理员审批');
    // admin 收到审批通知（幂等）
    const notices = await db.notification.findMany({ where: { recipientId: adminId, dedupeKey: `user-reg:${pending.id}` } });
    expect(notices).toHaveLength(1);
    expect(notices[0].type).toBe('USER_REGISTRATION');
    // 审批后登录成功
    await admin.post(`/api/users/${pending.id}/approve`).expect(201);
    await request(app.getHttpServer()).post('/api/auth/login').send({ username: regUsername, password: regPassword }).expect(201);
  });

  it('revokes sessions on disable and blocks disabled login', async () => {
    const user = await db.user.findUniqueOrThrow({ where: { username: regUsername } });
    const session = request.agent(app.getHttpServer());
    await session.post('/api/auth/login').send({ username: regUsername, password: regPassword }).expect(201);
    await session.get('/api/auth/me').expect(200);
    await admin.post(`/api/users/${user.id}/disable`).expect(201);
    // 旧会话立即失效
    await session.get('/api/auth/me').expect(401);
    const login = await request(app.getHttpServer()).post('/api/auth/login').send({ username: regUsername, password: regPassword }).expect(401);
    expect(login.body.message).toBe('账号已被禁用');
    // 恢复
    await admin.post(`/api/users/${user.id}/enable`).expect(201);
    await request(app.getHttpServer()).post('/api/auth/login').send({ username: regUsername, password: regPassword }).expect(201);
  });

  it('runs loan lifecycle: COMPANY devices loan with temporary attachment, return restores stock', async () => {
    const d1 = await db.device.create({ data: { ownerType: 'COMPANY', name: '借测相机1', serialNumber: `LN1-${suffix}` } });
    const d2 = await db.device.create({ data: { ownerType: 'COMPANY', name: '借测相机2', serialNumber: `LN2-${suffix}` } });
    const created = (await support.post('/api/loans').send({ organizationId: orgId, purpose: '现场评估', dueAt: '2030-01-01', deviceIds: [d1.id, d2.id] }).expect(201)).body;
    expect(created.loanNo).toMatch(/^LN-\d{6}-\d{3}$/);
    // 借测创建后设备临时挂靠到借测客户、状态 LOANED
    const loaned1 = await db.device.findUniqueOrThrow({ where: { id: d1.id } });
    expect(loaned1.status).toBe('LOANED');
    expect(loaned1.organizationId).toBe(orgId);
    // 客户资产不能创建借测单
    const customerDevice = await db.device.create({ data: { organizationId: orgId, name: '客户资产相机', serialNumber: `CA-${suffix}` } });
    const rejected = await support.post('/api/loans').send({ organizationId: orgId, purpose: '借用客户资产', dueAt: '2030-01-01', deviceIds: [customerDevice.id] }).expect(400);
    expect(rejected.body.message).toBe('客户资产不能创建借测单');
    // 非在库设备不能再借
    await support.post('/api/loans').send({ organizationId: orgId, purpose: '重复借出', dueAt: '2030-01-01', deviceIds: [d1.id] }).expect(400);
    // 指派 + 幂等通知
    await admin.post(`/api/loans/${created.id}/assign`).send({ assigneeId: employeeId }).expect(201);
    await admin.post(`/api/loans/${created.id}/assign`).send({ assigneeId: employeeId }).expect(201);
    expect(await db.notification.count({ where: { recipientId: employeeId, dedupeKey: `loan-assign:${created.id}:${employeeId}` } })).toBe(1);
    // 归还后回公司库存、解除临时挂靠
    const returned = (await support.post(`/api/loans/${created.id}/return`).send({ items: [{ deviceId: d1.id, conditionNote: '外观完好' }] }).expect(201)).body;
    expect(returned.status).toBe('RETURNED');
    expect(returned.returnedAt).toBeTruthy();
    const restored1 = await db.device.findUniqueOrThrow({ where: { id: d1.id } });
    expect(restored1.status).toBe('IN_STOCK');
    expect(restored1.organizationId).toBeNull();
    expect((await db.device.findUniqueOrThrow({ where: { id: d2.id } })).status).toBe('IN_STOCK');
  });

  it('lazily marks overdue loans and notifies once', async () => {
    const device = await db.device.create({ data: { ownerType: 'COMPANY', name: '逾期相机', serialNumber: `OD-${suffix}` } });
    const created = (await support.post('/api/loans').send({ organizationId: orgId, purpose: '逾期测试', loanedAt: '2020-01-01', dueAt: '2020-02-01', deviceIds: [device.id] }).expect(201)).body;
    expect(created.status).toBe('ONGOING');
    const listed = (await admin.get('/api/loans?status=OVERDUE').expect(200)).body;
    const found = listed.find((loan: { id: string }) => loan.id === created.id);
    expect(found).toBeTruthy();
    expect((await db.loanOrder.findUniqueOrThrow({ where: { id: created.id } })).status).toBe('OVERDUE');
    const supporter = await db.user.findUniqueOrThrow({ where: { username: 'support' } });
    expect(await db.notification.count({ where: { dedupeKey: `loan-overdue:${created.id}`, recipientId: supporter.id } })).toBe(1);
    // 再次列表不重复通知
    await admin.get('/api/loans').expect(200);
    expect(await db.notification.count({ where: { dedupeKey: `loan-overdue:${created.id}` } })).toBe(1);
  });

  it('hides other users loans from employee role', async () => {
    const all = (await employee.get('/api/loans').expect(200)).body;
    for (const loan of all) expect([loan.assigneeId, loan.createdById]).toContain(employeeId);
    const others = await db.loanOrder.findFirst({ where: { NOT: { OR: [{ assigneeId: employeeId }, { createdById: employeeId }] } } });
    if (others) await employee.get(`/api/loans/${others.id}`).expect(404);
  });

  it('enforces repair state machine and auto-fills warranty', async () => {
    const future = new Date(Date.now() + 365 * 86400_000);
    const device = await db.device.create({ data: { organizationId: orgId, name: '返修相机', serialNumber: `RP-${suffix}`, warrantyUntil: future } });
    const created = (await support.post('/api/repairs').send({ organizationId: orgId, serialNumber: device.serialNumber, symptom: '无法出图' }).expect(201)).body;
    expect(created.repairNo).toMatch(/^RP-\d{6}-\d{3}$/);
    expect(created.inWarranty).toBe(true);
    expect((await db.device.findUniqueOrThrow({ where: { id: device.id } })).status).toBe('REPAIRING');
    // 非法跳级流转
    await support.post(`/api/repairs/${created.id}/transition`).send({ status: 'SHIPPED', trackingNo: 'SF123' }).expect(400);
    // 逐级流转
    await support.post(`/api/repairs/${created.id}/transition`).send({ status: 'DIAGNOSING' }).expect(201);
    await support.post(`/api/repairs/${created.id}/transition`).send({ status: 'REPAIRING' }).expect(201);
    await support.post(`/api/repairs/${created.id}/transition`).send({ status: 'SHIPPED' }).expect(400); // 缺物流单号
    await support.post(`/api/repairs/${created.id}/transition`).send({ status: 'SHIPPED', trackingNo: 'SF123456' }).expect(201);
    await support.post(`/api/repairs/${created.id}/transition`).send({ status: 'CLOSED' }).expect(201);
    expect((await db.device.findUniqueOrThrow({ where: { id: device.id } })).status).toBe('IN_STOCK');
    const detail = (await support.get(`/api/repairs/${created.id}`).expect(200)).body;
    expect(detail.events.map((e: { type: string }) => e.type)).toContain('STATUS_CHANGE');
  });

  it('backfills ownerless CUSTOMER device organization on repair creation', async () => {
    const device = await db.device.create({ data: { ownerType: 'CUSTOMER', name: '无归属返修相机', serialNumber: `RB-${suffix}` } });
    expect(device.organizationId).toBeNull();
    const created = (await support.post('/api/repairs').send({ organizationId: orgId, serialNumber: device.serialNumber, symptom: '无法连接' }).expect(201)).body;
    expect(created.organization.id).toBe(orgId);
    const updated = await db.device.findUniqueOrThrow({ where: { id: device.id } });
    expect(updated.organizationId).toBe(orgId);
    expect(updated.status).toBe('REPAIRING');
    // COMPANY 设备建返修单时保持原归属不动
    const companyDevice = await db.device.create({ data: { ownerType: 'COMPANY', name: '公司样机返修', serialNumber: `RC-${suffix}` } });
    await support.post('/api/repairs').send({ organizationId: orgId, serialNumber: companyDevice.serialNumber, symptom: '镜头异响' }).expect(201);
    const untouched = await db.device.findUniqueOrThrow({ where: { id: companyDevice.id } });
    expect(untouched.organizationId).toBeNull();
    expect(untouched.ownerType).toBe('COMPANY');
  });

  it('rejects invalid device status transitions', async () => {
    const device = await db.device.create({ data: { organizationId: orgId, name: '状态机相机', serialNumber: `SM-${suffix}` } });
    await admin.patch(`/api/devices/${device.id}/status`).send({ status: 'REPAIRING' }).expect(400); // IN_STOCK 不能直达 REPAIRING
    await admin.patch(`/api/devices/${device.id}/status`).send({ status: 'RETIRED' }).expect(200);
    await admin.patch(`/api/devices/${device.id}/status`).send({ status: 'IN_STOCK' }).expect(400); // RETIRED 不可恢复
  });

  it('requires organization for CUSTOMER devices on creation', async () => {
    const res = await admin.post('/api/devices').send({ ownerType: 'CUSTOMER', name: '无归属客户资产' }).expect(400);
    expect(res.body.message).toBe('客户资产必须选择所属客户');
    const company = (await admin.post('/api/devices').send({ ownerType: 'COMPANY', name: '公司库存样机' }).expect(201)).body;
    expect(company.ownerType).toBe('COMPANY');
    expect(company.organization).toBeNull();
  });

  it('returns aggregated customer profile with object-level isolation', async () => {
    const profile = (await admin.get(`/api/customers/${orgId}/profile`).expect(200)).body;
    expect(profile.organization.id).toBe(orgId);
    expect(profile).toHaveProperty('contacts');
    expect(profile.loanOrders.length).toBeGreaterThan(0);
    expect(profile.repairOrders.length).toBeGreaterThan(0);
    // employee 非 owner 不可见
    await employee.get(`/api/customers/${orgId}/profile`).expect(404);
  });

  it('applies ticket visibility and edit rights by creator, assignee and admin', async () => {
    const base = { category: 'OTHER', organizationId: orgId, title: '权限模型改造验证', description: '权限模型改造验证' };
    // 创建时不指定负责人 → 默认为创建人
    const t1 = (await employee.post('/api/tickets').send(base).expect(201)).body;
    expect(t1.assignee?.id).toBe(employeeId);
    // 内部角色可见全部工单：employee 能看到 support 的工单
    const t2 = (await support.post('/api/tickets').send(base).expect(201)).body;
    expect((await employee.get('/api/tickets').expect(200)).body.items.some((t: { id: string }) => t.id === t2.id)).toBe(true);
    await employee.get(`/api/tickets/${t2.id}`).expect(200);
    // employee 非创建人/负责人：PATCH / status / 客户回复均 403
    await employee.patch(`/api/tickets/${t2.id}`).send({ title: '越权修改标题' }).expect(403);
    await employee.post(`/api/tickets/${t2.id}/status`).send({ status: 'IN_PROGRESS' }).expect(403);
    const denied = await employee.post(`/api/tickets/${t2.id}/events`).send({ type: 'CUSTOMER_REPLY', content: '越权客户回复' }).expect(403);
    expect(denied.body.message).toBe('仅创建人、负责人或管理员可以更新该工单');
    // employee 建单指定 support 为负责人：创建人非负责人仍可编辑，但不可转交
    const t3 = (await employee.post('/api/tickets').send({ ...base, title: '转交流程验证工单', description: '转交流程验证工单', assigneeId: supportId }).expect(201)).body;
    await employee.patch(`/api/tickets/${t3.id}`).send({ title: '创建人更新标题' }).expect(200);
    const transferDenied = await employee.patch(`/api/tickets/${t3.id}`).send({ assigneeId: adminId }).expect(403);
    expect(transferDenied.body.message).toBe('仅当前负责人或管理员可以转交工单');
    // 当前负责人 support 转交给 admin：成功 + 通知 + ASSIGNMENT 时间线事件
    await support.patch(`/api/tickets/${t3.id}`).send({ assigneeId: adminId }).expect(200);
    expect(await db.notification.count({ where: { recipientId: adminId, dedupeKey: `ticket-assign:${t3.id}:${adminId}` } })).toBe(1);
    const events = (await support.get(`/api/tickets/${t3.id}`).expect(200)).body.events as Array<{ type: string; content: string }>;
    expect(events.some((e) => e.type === 'ASSIGNMENT')).toBe(true);
    // admin 专属接口变更创建人，时间线留痕
    const changed = await admin.post(`/api/tickets/${t3.id}/created-by`).send({ createdById: supportId }).expect(201);
    expect(changed.body.createdBy.id).toBe(supportId);
    const timeline = (await admin.get(`/api/tickets/${t3.id}`).expect(200)).body.events as Array<{ type: string; content: string }>;
    const note = timeline.find((e) => e.content.includes('创建人由'));
    expect(note).toBeTruthy();
    expect(note!.content).toContain('变更为');
    // 非 admin 调 created-by 403
    await support.post(`/api/tickets/${t3.id}/created-by`).send({ createdById: supportId }).expect(403);
    await employee.post(`/api/tickets/${t3.id}/created-by`).send({ createdById: employeeId }).expect(403);
    await db.ticket.deleteMany({ where: { id: { in: [t1.id, t2.id, t3.id] } } });
  });

  it('allows any internal member to append internal notes but not customer replies on others tickets', async () => {
    const t = (await support.post('/api/tickets').send({ category: 'OTHER', organizationId: orgId, title: '协作备注验证工单', description: '协作备注验证工单' }).expect(201)).body;
    // employee 非创建人/负责人：INTERNAL_NOTE 允许（协作排查），强制内部可见
    const note = await employee.post(`/api/tickets/${t.id}/events`).send({ type: 'INTERNAL_NOTE', visibility: 'CUSTOMER', content: '协作排查备注' }).expect(201);
    expect(note.body.type).toBe('INTERNAL_NOTE');
    expect(note.body.visibility).toBe('INTERNAL');
    expect(note.body.author.id).toBe(employeeId);
    // CUSTOMER_REPLY 仍 403
    await employee.post(`/api/tickets/${t.id}/events`).send({ type: 'CUSTOMER_REPLY', content: '协作客户回复' }).expect(403);
    // 创建人/负责人不受限
    await support.post(`/api/tickets/${t.id}/events`).send({ type: 'INTERNAL_NOTE', content: '负责人备注' }).expect(201);
    await db.ticket.deleteMany({ where: { id: t.id } });
  });
});
