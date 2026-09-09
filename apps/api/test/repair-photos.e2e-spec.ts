import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import request, { type Agent } from 'supertest';
import { randomUUID } from 'node:crypto';
import { writeFile, readdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { AppModule } from '../src/app.module.js';
import { PrismaService } from '../src/prisma/prisma.service.js';

describe('Return PDF and loan photos', () => {
  let app: INestApplication; let db: PrismaService; let admin: Agent; let employee: Agent;
  let repairId: string; let itemId: string; let photoId: string;
  const suffix = randomUUID();
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9XQAAAAASUVORK5CYII=', 'base64');
  const upload = (category: string, key = randomUUID()) => admin.post(`/api/files/loan-items/${itemId}`).field('category', category).field('photoKey', key).attach('file', png, { filename: 'device.png', contentType: 'image/png' });
  beforeAll(async () => {
    if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) throw Error('isolated schema required');
    const module = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = module.createNestApplication(); app.setGlobalPrefix('api'); app.use(cookieParser());
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })); await app.init();
    db = app.get(PrismaService); admin = request.agent(app.getHttpServer()); employee = request.agent(app.getHttpServer());
    await admin.post('/api/auth/login').send({ username: 'admin', password: process.env.SEED_ADMIN_PASSWORD }).expect(201);
    await employee.post('/api/auth/login').send({ username: 'employee', password: process.env.SEED_EMPLOYEE_PASSWORD }).expect(201);
    const org = await db.customerOrganization.create({ data: { name: `表单测试-${suffix}` } });
    const device = await db.device.create({ data: { name: '返修相机', organizationId: org.id, serialNumber: `R-${suffix}` } });
    const loanDevice = await db.device.create({ data: { name: '借测相机', ownerType: 'COMPANY', serialNumber: `L-${suffix}` } });
    const loan = (await admin.post('/api/loans').send({ organizationId: org.id, deviceIds: [loanDevice.id], purpose: '照片测试', dueAt: '2030-01-01' }).expect(201)).body;
    itemId = loan.items[0].id;
    const repair = (await admin.post('/api/repairs').send({ organizationId: org.id, deviceId: device.id, symptom: '相机无法获取点云，重启后仍异常。', returnForm: { companyName: '测试公司', reportedAt: '2026-09-08', reporterName: '张三', reporterPhone: '13800000000', serialNumber: device.serialNumber, appearance: '外观完整，无明显磕碰', returnAddress: '深圳市测试路 1 号，张三，13800000000', salesContact: '李辉', afterSalesContact: '刘海焕' } }).expect(201)).body;
    repairId = repair.id;
  });
  afterAll(async () => { await app?.close(); });
  it('persists all form fields and archives a downloadable PDF with an event', async () => {
    const pdf = (await admin.post(`/api/repairs/${repairId}/pdf`).expect(201)).body;
    expect(pdf.mimeType).toBe('application/pdf');
    const response = await admin.get(`/api/files/${pdf.id}`).expect(200);
    expect(response.body.subarray(0, 4).toString()).toBe('%PDF');
    await writeFile(resolve(process.env.UPLOAD_DIR!, 'sample-return.pdf'), response.body);
    const detail = (await admin.get(`/api/repairs/${repairId}`).expect(200)).body;
    expect(detail.returnForm.reporterName).toBe('张三');
    expect(detail.attachments.some((a: { id: string }) => a.id === pdf.id)).toBe(true);
    expect(detail.events.some((e: { content: string }) => e.content.includes('归档'))).toBe(true);
  });
  it('enforces 9/5/1 category limits and upload idempotency', async () => {
    const key = randomUUID();
    const first = (await upload('VIEWS', key).expect(201)).body;
    photoId = first.id;
    expect((await upload('VIEWS', key).expect(201)).body.id).toBe(first.id);
    for (let i = 1; i < 9; i++) await upload('VIEWS').expect(201);
    await upload('VIEWS').expect(400);
    for (let i = 0; i < 5; i++) await upload('ACCESSORIES').expect(201);
    await upload('ACCESSORIES').expect(400);
    const parallel = await Promise.all([upload('SERIAL'), upload('SERIAL')]);
    expect(parallel.map(r => r.status).sort()).toEqual([201, 400]);
    expect(await db.attachment.count({ where: { loanItemId: itemId } })).toBe(15);
  });
  it('rejects unauthorized upload/download and cleans rejected files', async () => {
    const before = await readdir(process.env.UPLOAD_DIR!);
    await employee.post(`/api/files/loan-items/${itemId}`).field('category', 'SERIAL').field('photoKey', randomUUID()).attach('file', png, { filename: 'test.png', contentType: 'image/png' }).expect(404);
    await employee.get(`/api/files/${photoId}`).expect(404);
    await employee.post(`/api/repairs/${repairId}/pdf`).expect(404);
    await upload('INVALID').expect(400);
    await admin.post(`/api/files/loan-items/${itemId}`).field('category', 'VIEWS').field('photoKey', randomUUID()).attach('file', Buffer.from('fake'), { filename: 'fake.png', contentType: 'image/png' }).expect(400);
    expect((await readdir(process.env.UPLOAD_DIR!)).sort()).toEqual(before.sort());
  });
});
