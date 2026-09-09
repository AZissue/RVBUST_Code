import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import dotenv from 'dotenv';
import ExcelJS from 'exceljs';
import request, { type Agent } from 'supertest';
import { randomUUID } from 'node:crypto';
import { AppModule } from '../src/app.module.js';
import { PrismaService } from '../src/prisma/prisma.service.js';

dotenv.config({ path: '../../.env' });

describe('Ticket excel template export and batch import (e2e)', () => {
  let app: INestApplication; let db: PrismaService;
  let admin: Agent;
  const suffix = randomUUID().slice(0, 8);

  beforeAll(async () => {
    if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) throw new Error('Requires isolated quick_ticket_test schema');
    const module = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = module.createNestApplication(); app.setGlobalPrefix('api'); app.use(cookieParser());
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })); await app.init();
    db = app.get(PrismaService);
    await db.ticket.deleteMany({ where: { OR: [{ number: { startsWith: 'RVC-260901-' } }, { number: { startsWith: 'RVC-260828-' } }] } });
    admin = request.agent(app.getHttpServer());
    await admin.post('/api/auth/login').send({ username: 'admin', password: process.env.SEED_ADMIN_PASSWORD }).expect(201);
  });

  afterAll(async () => { await app?.close(); });

  it('exports a template and imports filled rows with numbers derived from the filled time', async () => {
    const exported = await admin.get('/api/tickets/import-template').buffer(true).parse((response, callback) => {
      const chunks: Buffer[] = [];
      response.on('data', (chunk: Buffer) => chunks.push(chunk));
      response.on('end', () => callback(null, Buffer.concat(chunks)));
    }).expect(200);
    expect(exported.headers['content-type']).toContain('spreadsheetml');
    const template = exported.body as unknown as Buffer;

    const workbook = await new ExcelJS.Workbook().xlsx.load(template as unknown as ExcelJS.Buffer);
    const sheet = workbook.worksheets[0];
    expect(sheet.getRow(1).getCell(1).text).toBe('时间');
    const adminName = (await db.user.findUniqueOrThrow({ where: { username: 'admin' }, select: { name: true } })).name;
    // 示例行应被导入忽略
    const row3 = sheet.getRow(3);
    row3.values = ['2026-09-01', `Excel导入客户-${suffix}`, 'M2600 连接超时', '相机通电后搜索不到设备，换网线复现', '硬件故障', adminName, '高', 'M2600', `SN-${suffix}`, 'RVC 2.8', 'Windows 11', '2026-09-10', '原始描述A'];
    const row4 = sheet.getRow(4);
    row4.values = ['2026-09-01', `Excel导入客户-${suffix}`, '', '第二个问题描述内容', '', '', '', '', '', '', '', '', ''];
    const row5 = sheet.getRow(5);
    row5.values = ['2026-08-28', `Excel导入客户-${suffix}`, '历史问题', '八月底的历史工单', '售前咨询', '', '', '', '', '', '', '', ''];
    const row6 = sheet.getRow(6);
    row6.values = ['2026-09-02', `Excel导入客户-${suffix}`, '坏分类行', '这行分类非法应失败', '不存在的分类', '', '', '', '', '', '', '', ''];
    const row7 = sheet.getRow(7);
    row7.values = ['2026-09-02', '', '无客户行', '这行缺客户应失败', '', '', '', '', '', '', '', '', ''];
    const buffer = Buffer.from(await workbook.xlsx.writeBuffer());

    const result = (await admin.post('/api/tickets/import').attach('file', buffer, 'import.xlsx').expect(201)).body as { created: number; failed: Array<{ row: number; reason: string }> };
    expect(result.created).toBe(3);
    expect(result.failed).toHaveLength(2);
    expect(result.failed.map((f) => f.row).sort()).toEqual([6, 7]);
    expect(result.failed.find((f) => f.row === 6)!.reason).toContain('问题分类');

    // 编号按填写时间：同日的两张连续，历史日期独立编号
    const org = await db.customerOrganization.findFirstOrThrow({ where: { name: `Excel导入客户-${suffix}` } });
    const tickets = await db.ticket.findMany({ where: { organizationId: org.id }, orderBy: { number: 'asc' } });
    expect(tickets.map((t) => t.number)).toEqual([`RVC-260828-001`, `RVC-260901-001`, `RVC-260901-002`]);
    const first = await db.ticket.findUniqueOrThrow({ where: { id: tickets[1].id }, include: { organization: true, events: true } });
    const firstDate = first.createdAt
    expect(`${firstDate.getFullYear()}-${firstDate.getMonth() + 1}-${firstDate.getDate()}`).toBe('2026-9-1');
    expect(first.organization.name).toBe(`Excel导入客户-${suffix}`);
    expect(first.priority).toBe('HIGH');
    expect(first.category).toBe('HARDWARE_FAILURE');
    expect(first.title).toBe('M2600 连接超时');
    expect(first.rawText).toBe('原始描述A');
    expect(first.events.some((e) => e.content.includes('Excel'))).toBe(true);
    // 标题留空 → 取描述前 50 字
    const second = await db.ticket.findUniqueOrThrow({ where: { id: tickets[2].id } });
    expect(second.title).toBe('第二个问题描述内容');
    expect(second.category).toBe('OTHER');
    expect(second.assigneeId).toBe(first.createdById);
    await db.ticket.deleteMany({ where: { id: { in: tickets.map((t) => t.id) } } });
    await db.customerOrganization.deleteMany({ where: { name: `Excel导入客户-${suffix}` } });
  });

  it('rejects wrong headers and non-xlsx files', async () => {
    const badBook = new ExcelJS.Workbook();
    const badSheet = badBook.addWorksheet('x');
    badSheet.addRow(['完全', '不对', '的表头']);
    badSheet.addRow(['a', 'b', 'c']);
    const badBuffer = Buffer.from(await badBook.xlsx.writeBuffer());
    const rejected = await admin.post('/api/tickets/import').attach('file', badBuffer, 'bad.xlsx').expect(400);
    expect(rejected.body.message).toContain('表头缺少必填列');
    await admin.post('/api/tickets/import').attach('file', Buffer.from('not excel'), 'bad.txt').expect(400);
  });
});
