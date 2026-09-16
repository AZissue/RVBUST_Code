import { INestApplication, ValidationPipe } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import cookieParser from 'cookie-parser';
import request, { type Agent } from 'supertest';
import { AppModule } from '../src/app.module.js';
import { PrismaService } from '../src/prisma/prisma.service.js';

/**
 * 工单 ↔ 借测/维修联动闭环：
 * 维修线——HARDWARE_FAILURE 工单勾选 createLinkedRepair 自动建单 → 时间线 LINK_CREATED + 通知
 *   → 维修单流转 DIAGNOSING 回写 LINK_UPDATE → 进行中时工单 RESOLVED 被 400 拦截
 *   → 走完 SHIPPED（补物流单号）/CLOSED（补处理说明）→ RESOLVED 放行；
 * 借测线——LOAN_REQUEST 工单勾选 createLinkedLoan → loan-requests 幂等 → cancel → LINK_UPDATE。
 */
describe('Ticket ↔ loan/repair linkage (e2e)', () => {
  let app: INestApplication; let db: PrismaService; let admin: Agent;
  let orgId: string;
  const ticketIds: string[] = [];
  const deviceIds: string[] = [];
  beforeAll(async () => {
    if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) throw Error('isolated schema required');
    const module = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = module.createNestApplication(); app.setGlobalPrefix('api'); app.use(cookieParser());
    app.useGlobalPipes(new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })); await app.init();
    db = app.get(PrismaService);
    admin = request.agent(app.getHttpServer());
    await admin.post('/api/auth/login').send({ username: 'admin', password: process.env.SEED_ADMIN_PASSWORD }).expect(201);
    orgId = (await db.customerOrganization.findFirstOrThrow({ where: { name: '华东智能制造示例客户' } })).id;
  });
  afterAll(async () => {
    // 清理本 spec 创建的工单与关联单据（隔离 schema，直接按主键删除）
    await db.followUp.deleteMany({ where: { ticketId: { in: ticketIds } } });
    await db.attachment.deleteMany({ where: { repairOrder: { ticketId: { in: ticketIds } } } });
    await db.loanOrder.deleteMany({ where: { ticketId: { in: ticketIds } } });
    await db.repairOrder.deleteMany({ where: { ticketId: { in: ticketIds } } });
    await db.ticket.deleteMany({ where: { id: { in: ticketIds } } });
    await db.device.deleteMany({ where: { id: { in: deviceIds } } });
    await app?.close();
  });
  const createTicket = async (body: Record<string, unknown>) => {
    const ticket = (await admin.post('/api/tickets').send({ organizationId: orgId, ...body }).expect(201)).body;
    ticketIds.push(ticket.id);
    return ticket;
  };

  it('closes the repair loop: auto-create → timeline/notify → DIAGNOSING sync → RESOLVED blocked → CLOSED → RESOLVED allowed', async () => {
    const ticket = await createTicket({
      category: 'HARDWARE_FAILURE', title: 'M2600 无法上电', description: '客户反馈相机无法上电，疑似硬件故障，需返修排查',
      serialNumber: 'SN-M4-LINKAGE-001', createLinkedRepair: true,
    });
    expect(ticket.linkageErrors).toBeUndefined();
    // 联动卡片出现维修单；时间线记录 LINK_CREATED；通知生成给 admin
    const links = (await admin.get(`/api/tickets/${ticket.id}/links`).expect(200)).body;
    expect(links.repairs).toHaveLength(1);
    expect(links.repairs[0].status).toBe('RECEIVED');
    const repairId = links.repairs[0].id;
    const linkCreated = await db.ticketEvent.findFirstOrThrow({ where: { ticketId: ticket.id, type: 'LINK_CREATED' } });
    expect(linkCreated.content).toContain(links.repairs[0].repairNo);
    expect(await db.notification.count({ where: { ticketId: ticket.id, type: 'LINK_REPAIR_CREATED' } })).toBeGreaterThan(0);
    // 维修单流转到 DIAGNOSING → 工单时间线出现 LINK_UPDATE 回写
    await admin.post(`/api/repairs/${repairId}/transition`).send({ status: 'DIAGNOSING' }).expect(201);
    const diagnosing = await db.ticketEvent.findFirstOrThrow({ where: { ticketId: ticket.id, type: 'LINK_UPDATE', content: { contains: '诊断中' } } });
    expect(diagnosing.metadata && JSON.stringify(diagnosing.metadata)).toContain('DIAGNOSING');
    // 存在进行中维修单时工单 RESOLVED 被拦截
    await admin.post(`/api/tickets/${ticket.id}/status`).send({ status: 'RESOLVED' }).expect(400);
    // 走完维修闭环：REPAIRING → SHIPPED（补物流单号）→ CLOSED（补处理说明）
    await admin.post(`/api/repairs/${repairId}/transition`).send({ status: 'REPAIRING' }).expect(201);
    await admin.post(`/api/repairs/${repairId}/transition`).send({ status: 'SHIPPED', trackingNo: 'SF-M4-260916-001' }).expect(201);
    await admin.post(`/api/repairs/${repairId}/transition`).send({ status: 'CLOSED', content: '已更换电源板并老化测试通过' }).expect(201);
    expect((await db.repairOrder.findUniqueOrThrow({ where: { id: repairId } })).status).toBe('CLOSED');
    const closedEvent = await db.ticketEvent.findFirstOrThrow({ where: { ticketId: ticket.id, type: 'LINK_UPDATE', content: { contains: '已关闭' } } });
    expect(closedEvent).toBeTruthy();
    // 维修单完结后 RESOLVED 放行
    await admin.post(`/api/tickets/${ticket.id}/status`).send({ status: 'RESOLVED' }).expect(201);
    expect((await db.ticket.findUniqueOrThrow({ where: { id: ticket.id } })).status).toBe('RESOLVED');
  });

  it('closes the loan loop: auto-create → idempotent loan-requests → cancel → LINK_UPDATE', async () => {
    const ticket = await createTicket({
      category: 'LOAN_REQUEST', title: 'M2600 借测申请', description: '客户希望借测 M2600 评估点云质量',
      createLinkedLoan: true,
    });
    expect(ticket.linkageErrors).toBeUndefined();
    const links = (await admin.get(`/api/tickets/${ticket.id}/links`).expect(200)).body;
    expect(links.loans).toHaveLength(1);
    const loanId = links.loans[0].id;
    await db.ticketEvent.findFirstOrThrow({ where: { ticketId: ticket.id, type: 'LINK_CREATED', content: { contains: links.loans[0].loanNo } } });
    expect(await db.notification.count({ where: { ticketId: ticket.id, type: 'LINK_LOAN_CREATED' } })).toBeGreaterThan(0);
    // 幂等：重复 POST loan-requests 返回同一张进行中的借测单，不产生新单
    const again = (await admin.post(`/api/tickets/${ticket.id}/loan-requests`).expect(201)).body;
    expect(again.loan.id).toBe(loanId);
    expect(await db.loanOrder.count({ where: { ticketId: ticket.id } })).toBe(1);
    // 取消借测单 → 状态 CANCELLED + 工单时间线 LINK_UPDATE 回写
    await admin.post(`/api/loans/${loanId}/cancel`).expect(201);
    expect((await db.loanOrder.findUniqueOrThrow({ where: { id: loanId } })).status).toBe('CANCELLED');
    await db.ticketEvent.findFirstOrThrow({ where: { ticketId: ticket.id, type: 'LINK_UPDATE', content: { contains: '已取消' } } });
    // 子单全部完结后可标记解决
    await admin.post(`/api/tickets/${ticket.id}/status`).send({ status: 'RESOLVED' }).expect(201);
  });

  it('repair fallback: 无设备无SN有型号时自动建 MANUAL 设备档案并创建 RP 单', async () => {
    const ticket = await createTicket({
      category: 'HARDWARE_FAILURE', title: 'M2600 图像花屏', description: '客户反馈相机图像花屏，需返修排查',
      cameraModel: 'M2600', createLinkedRepair: true,
    });
    expect(ticket.linkageErrors).toBeUndefined();
    const links = (await admin.get(`/api/tickets/${ticket.id}/links`).expect(200)).body;
    expect(links.repairs).toHaveLength(1);
    // 自动建档：MANUAL 来源、客户资产、归属本客户组织，名称/型号均为工单型号
    const repair = await db.repairOrder.findUniqueOrThrow({ where: { id: links.repairs[0].id } });
    const device = await db.device.findUniqueOrThrow({ where: { id: repair.deviceId! } });
    deviceIds.push(device.id);
    expect(device.source).toBe('MANUAL');
    expect(device.ownerType).toBe('CUSTOMER');
    expect(device.organizationId).toBe(orgId);
    expect(device.name).toBe('M2600');
    expect(device.cameraModel).toBe('M2600');
    expect(device.notes).toContain('自动建档');
    await db.ticketEvent.findFirstOrThrow({ where: { ticketId: ticket.id, type: 'LINK_CREATED', content: { contains: links.repairs[0].repairNo } } });
  });

  it('repair failure: 无设备无SN无型号时留痕时间线并通知（linkageErrors 反馈前端）', async () => {
    const ticket = await createTicket({
      category: 'HARDWARE_FAILURE', title: 'M2600 无法识别', description: '客户反馈相机无法识别，需返修排查',
      createLinkedRepair: true,
    });
    expect(Array.isArray(ticket.linkageErrors)).toBe(true);
    expect(ticket.linkageErrors[0]).toContain('维修单创建失败');
    // 工单时间线留痕：INTERNAL_NOTE + 失败元数据
    const failed = await db.ticketEvent.findFirstOrThrow({
      where: { ticketId: ticket.id, type: 'INTERNAL_NOTE', content: { contains: '联动创建维修单失败' } },
    });
    expect(failed.visibility).toBe('INTERNAL');
    expect(failed.metadata && JSON.stringify(failed.metadata)).toContain('FAILED');
    // 负责人（无负责人退创建人）与 admin 收到 LINK_FAILED 通知
    expect(await db.notification.count({ where: { ticketId: ticket.id, type: 'LINK_FAILED' } })).toBeGreaterThan(0);
  });

  it('非 UUID 路径参数返回 400 而非 500', async () => {
    await admin.get('/api/tickets/abc').expect(400);
  });
});
