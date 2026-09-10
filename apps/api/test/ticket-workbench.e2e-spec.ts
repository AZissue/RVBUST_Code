import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import request, { type Agent } from 'supertest';
import { AppModule } from '../src/app.module.js';
import { PrismaService } from '../src/prisma/prisma.service.js';

describe('Ticket workbench safety', () => {
  let app: INestApplication; let db: PrismaService; let admin: Agent; let employee: Agent; let customer: Agent;
  let employeeId: string; let orgId: string;
  beforeAll(async () => {
    if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) throw Error('isolated schema required');
    const module = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = module.createNestApplication(); app.setGlobalPrefix('api'); app.use(cookieParser());
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })); await app.init();
    db = app.get(PrismaService);
    admin = request.agent(app.getHttpServer()); employee = request.agent(app.getHttpServer()); customer = request.agent(app.getHttpServer());
    await admin.post('/api/auth/login').send({ username: 'admin', password: process.env.SEED_ADMIN_PASSWORD }).expect(201);
    await employee.post('/api/auth/login').send({ username: 'employee', password: process.env.SEED_EMPLOYEE_PASSWORD }).expect(201);
    await customer.post('/api/auth/login').send({ username: 'customer', password: process.env.SEED_CUSTOMER_PASSWORD }).expect(201);
    employeeId = (await db.user.findUniqueOrThrow({ where: { username: 'employee' } })).id;
    orgId = (await db.user.findUniqueOrThrow({ where: { username: 'customer' } })).customerOrganizationId!;
  });
  afterAll(async () => { await app?.close(); });
  const create = async () => (await admin.post('/api/tickets').send({ organizationId: orgId, category: 'OTHER', title: '回归工单' + Date.now(), description: '工作台回归测试', assigneeId: employeeId }).expect(201)).body;
  it('only admins hide individual timeline records with audit and without changing state', async () => {
    const t = await create();
    await admin.post(`/api/tickets/${t.id}/assist-requests`).send({ targetUserIds: [employeeId], message: '测试邀请' }).expect(201);
    const event = await db.ticketEvent.findFirstOrThrow({ where: { ticketId: t.id, type: 'ASSIST_REQUEST' } });
    const endpoint = `/api/tickets/${t.id}/events/${event.id}`;
    await employee.delete(endpoint).send({ reason: '测试记录' }).expect(403);
    await customer.delete(endpoint).send({ reason: '测试记录' }).expect(403);
    await admin.delete(endpoint).send({ reason: '  ' }).expect(400);
    const another = await create();
    await admin.delete(`/api/tickets/${another.id}/events/${event.id}`).send({ reason: '不属于此工单' }).expect(404);
    await db.ticket.update({ where: { id: t.id }, data: { status: 'CLOSED' } });
    const before = await db.ticket.findUniqueOrThrow({ where: { id: t.id } });
    await admin.delete(endpoint).send({ reason: '清理测试邀请的时间线' }).expect(200);
    const detail = (await admin.get(`/api/tickets/${t.id}`).expect(200)).body;
    expect(detail.events.some((item: { id: string }) => item.id === event.id)).toBe(false);
    expect(detail.status).toBe('CLOSED');
    expect(detail.assistRequests[0].status).toBe('PENDING');
    expect((await db.ticket.findUniqueOrThrow({ where: { id: t.id } })).updatedAt).toEqual(before.updatedAt);
    const stored = await db.ticketEvent.findUniqueOrThrow({ where: { id: event.id } });
    expect(stored.content).toBe(event.content);
    const audit = await db.auditLog.findFirstOrThrow({ where: { action: 'ticket.event.delete', entityId: event.id } });
    expect(JSON.stringify(audit.metadata)).toContain('清理测试邀请的时间线');
    expect(JSON.stringify(audit.metadata)).toContain(event.content);
    await admin.delete(endpoint).send({ reason: '再次删除' }).expect(409);
  });
  it('keeps internal invitations out of customer detail and lists', async () => {
    const t = await create();
    await admin.post(`/api/tickets/${t.id}/assist-requests`).send({ targetUserIds: [employeeId], message: '内部保密说明' }).expect(201);
    for (const url of [`/api/tickets/${t.id}`, `/api/tickets?search=${t.number}`, `/api/tickets?all=1&search=${t.number}`]) {
      const response = await customer.get(url).expect(200);
      expect(JSON.stringify(response.body)).not.toContain('内部保密说明');
      expect(JSON.stringify(response.body)).not.toContain('assistRequests');
    }
  });
  it('allows delete/restore/delete and excludes trash from the dashboard', async () => {
    const t = await create();
    const before = (await employee.get('/api/dashboard').expect(200)).body.ticketCounts.pending;
    await admin.delete(`/api/tickets/${t.id}`).send({ reason: '重复记录' }).expect(200);
    expect((await employee.get('/api/dashboard').expect(200)).body.ticketCounts.pending).toBe(before - 1);
    await customer.get(`/api/tickets/${t.id}`).expect(404);
    await admin.post(`/api/tickets/${t.id}/restore`).expect(201);
    await admin.delete(`/api/tickets/${t.id}`).send({ reason: '再次删除' }).expect(200);
    expect(await db.notification.count({ where: { ticketId: t.id, recipientId: employeeId, type: 'TICKET_DELETED' } })).toBe(2);
  });
  it('prevents duplicate invitations and accepts only one concurrent outcome', async () => {
    const t = await create();
    await admin.post(`/api/tickets/${t.id}/assist-requests`).send({ targetUserIds: [employeeId] }).expect(201);
    await admin.post(`/api/tickets/${t.id}/assist-requests`).send({ targetUserIds: [employeeId] }).expect(409);
    const invite = await db.ticketAssistRequest.findFirstOrThrow({ where: { ticketId: t.id } });
    const results = await Promise.all([
      employee.post(`/api/tickets/${t.id}/assist-requests/${invite.id}/accept`),
      employee.post(`/api/tickets/${t.id}/assist-requests/${invite.id}/reject`).send({ reason: '当前无法协助' }),
    ]);
    expect(results.filter(r => r.status === 201)).toHaveLength(1);
    expect(results.filter(r => [400, 409].includes(r.status))).toHaveLength(1);
    const final = await db.ticketAssistRequest.findUniqueOrThrow({ where: { id: invite.id } });
    expect(await db.ticketCollaborator.count({ where: { ticketId: t.id, userId: employeeId } })).toBe(final.status === 'ACCEPTED' ? 1 : 0);
  });
  it('does not allow accepting an invitation on a deleted ticket', async () => {
    const t = await create();
    await admin.post(`/api/tickets/${t.id}/assist-requests`).send({ targetUserIds: [employeeId] }).expect(201);
    const invite = await db.ticketAssistRequest.findFirstOrThrow({ where: { ticketId: t.id } });
    await admin.delete(`/api/tickets/${t.id}`).send({}).expect(200);
    await employee.post(`/api/tickets/${t.id}/assist-requests/${invite.id}/accept`).expect(400);
    expect(await db.ticketCollaborator.count({ where: { ticketId: t.id, userId: employeeId } })).toBe(0);
  });
  it('filters invitations and preserves metrics when a status is selected', async () => {
    const t = await create();
    await admin.post(`/api/tickets/${t.id}/assist-requests`).send({ targetUserIds: [employeeId] }).expect(201);
    const invited = (await employee.get(`/api/tickets?view=invited&search=${t.number}`).expect(200)).body;
    expect(invited.items.map((item: { id: string }) => item.id)).toContain(t.id);
    const hidden = (await employee.get(`/api/tickets?view=assigned&search=${t.number}&status=RESOLVED`).expect(200)).body;
    expect(hidden.items).toHaveLength(0); expect(hidden.byStatus.PENDING).toBe(1);
    const todo = (await employee.get('/api/tickets?view=today-todo').expect(200)).body.total;
    expect((await employee.get('/api/dashboard').expect(200)).body.ticketCounts.todayTodo).toBe(todo);
  });
});
