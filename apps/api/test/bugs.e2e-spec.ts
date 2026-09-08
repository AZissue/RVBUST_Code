import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import dotenv from 'dotenv';
import request, { type Agent } from 'supertest';
import { randomUUID } from 'node:crypto';
import { AppModule } from '../src/app.module.js';
import { PrismaService } from '../src/prisma/prisma.service.js';

dotenv.config({ path: '../../.env' });

describe('Bug reports (e2e)', () => {
  let app: INestApplication; let db: PrismaService;
  let admin: Agent; let support: Agent; let employee: Agent;
  let employeeId: string;
  const suffix = randomUUID().slice(0, 8);

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
    employeeId = (await db.user.findUniqueOrThrow({ where: { username: 'employee' } })).id;
  });

  afterAll(async () => { await app?.close(); });

  it('lets any user file a bug with sequential number, visible to all, fixed only by admin', async () => {
    const created = (await employee.post('/api/bugs').send({ title: `页面白屏-${suffix}`, description: '打开工单列表时页面白屏，控制台报内存错误，复现概率约一半。' }).expect(201)).body;
    expect(created.bugNo).toMatch(/^BG-\d{6}-\d{3}$/);
    expect(created.status).toBe('OPEN');
    expect(created.author.id).toBe(employeeId);
    const bugId = created.id;
    // 所有用户可见
    expect((await support.get('/api/bugs').expect(200)).body.some((b: { id: string }) => b.id === bugId)).toBe(true);
    expect((await admin.get('/api/bugs').expect(200)).body.some((b: { id: string }) => b.id === bugId)).toBe(true);
    // 未登录不可见
    await request(app.getHttpServer()).get('/api/bugs').expect(401);
    // 非管理员不可标记修复
    await employee.patch(`/api/bugs/${bugId}/status`).send({ status: 'FIXED' }).expect(403);
    await support.patch(`/api/bugs/${bugId}/status`).send({ status: 'FIXED' }).expect(403);
    // mine=1 只返回自己提交的
    expect((await employee.get('/api/bugs?mine=1').expect(200)).body.every((b: { author: { id: string } }) => b.author.id === employeeId)).toBe(true);
    // 管理员：修复中 → 已修复，记录处理人/时间并通知提交人
    await admin.patch(`/api/bugs/${bugId}/status`).send({ status: 'IN_PROGRESS' }).expect(200);
    const fixed = (await admin.patch(`/api/bugs/${bugId}/status`).send({ status: 'FIXED' }).expect(200)).body;
    expect(fixed.status).toBe('FIXED');
    expect(fixed.resolver.name).toBeTruthy();
    expect(fixed.resolvedAt).toBeTruthy();
    const notice = await db.notification.findMany({ where: { recipientId: employeeId, dedupeKey: `bug-fixed:${bugId}` } });
    expect(notice).toHaveLength(1);
    expect(notice[0].type).toBe('BUG_FIXED');
    // 状态过滤
    expect((await admin.get('/api/bugs?status=OPEN').expect(200)).body.some((b: { id: string }) => b.id === bugId)).toBe(false);
    expect((await admin.get('/api/bugs?status=FIXED').expect(200)).body.some((b: { id: string }) => b.id === bugId)).toBe(true);
    // 非法状态与空描述被拒
    await admin.patch(`/api/bugs/${bugId}/status`).send({ status: 'DONE' }).expect(400);
    await employee.post('/api/bugs').send({ title: 'x', description: '   ' }).expect(400);
    await db.bugReport.delete({ where: { id: bugId } });
  });
});
