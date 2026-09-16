import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { LoanStatus, type Prisma } from '@prisma/client';
import ExcelJS from 'exceljs';
import type { AuthUser } from '../auth/auth.types.js';
import { NotificationsService } from '../notifications/notifications.service.js';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';
import { dateSerialPrefix, nextSerial } from '../common/numbering.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { AddFollowUpDto, AdvanceLoanDto, AssignLoanDto, CreateLoanDto, ReturnLoanDto, ScoreLoanDto, ShipLoanDto, UpdateLoanDto } from './dto/loan.dto.js';

const loanInclude = {
  organization: { select: { id: true, name: true } },
  contact: { select: { id: true, name: true, phone: true } },
  assignee: { select: { id: true, name: true } },
  ticket: { select: { id: true, number: true, title: true } },
  advancedBy: { select: { id: true, name: true } },
  followUps: { include: { author: { select: { id: true, name: true } } }, orderBy: { occurredAt: 'desc' as const } },
  items: { include: { attachments: { orderBy: { photoSlot: 'asc' as const } }, device: { select: { id: true, name: true, serialNumber: true, cameraModel: true, status: true } } } },
} as const;

// 排队位次动态计算：手动提前优先 → 评分降序（无评分最后）→ 先创建先服务
const QUEUE_ORDER_BY: Prisma.LoanOrderOrderByWithRelationInput[] = [
  { advancedAt: { sort: 'asc', nulls: 'last' } },
  { score: { sort: 'desc', nulls: 'last' } },
  { createdAt: 'asc' },
];

const ACTIVE_STATUSES: LoanStatus[] = [LoanStatus.ONGOING, LoanStatus.OVERDUE];
const dayMs = 86400000;

/** 业务日（Asia/Shanghai 零点，UTC） */
export function businessDay(now = new Date()) {
  return new Date(now.toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' }) + 'T00:00:00Z');
}

function parseMonth(value: string) {
  if (!/^\d{4}-\d{2}$/.test(value)) return null;
  const [year, month] = value.split('-').map(Number);
  if (month < 1 || month > 12) return null;
  return { start: new Date(Date.UTC(year, month - 1, 1)), end: new Date(Date.UTC(year, month, 1)) };
}

const LOAN_STATUS_LABELS: Record<LoanStatus, string> = { QUEUED: '排队中', ONGOING: '借测中', OVERDUE: '已逾期', RETURNED: '已归还', CANCELLED: '已取消' };

@Injectable()
export class LoansService {
  constructor(private readonly prisma: PrismaService, private readonly notifications: NotificationsService) {}

  private scopeWhere(user: AuthUser): Prisma.LoanOrderWhereInput {
    if (user.role === 'employee') return { OR: [{ assigneeId: user.id }, { createdById: user.id }] };
    return {};
  }

  private requireInternal(_user: AuthUser) {}

  // 惰性逾期修正：ONGOING 且 dueAt 已过的单置为 OVERDUE，并幂等通知创建人与负责人
  private async fixOverdue() {
    const now = new Date();
    const overdue = await this.prisma.loanOrder.findMany({ where: { status: LoanStatus.ONGOING, dueAt: { lt: now } }, select: { id: true, loanNo: true, createdById: true, assigneeId: true } });
    if (!overdue.length) return;
    await this.prisma.loanOrder.updateMany({ where: { id: { in: overdue.map((loan) => loan.id) }, status: LoanStatus.ONGOING, dueAt: { lt: now } }, data: { status: LoanStatus.OVERDUE } });
    await Promise.all(overdue.flatMap((loan) => [...new Set([loan.createdById, loan.assigneeId].filter(Boolean) as string[])].map((recipientId) =>
      this.notifications.notify({ recipientId, type: NOTIFICATION_TYPES.LOAN_OVERDUE, severity: 'WARNING', title: '借出单已逾期', body: `借出单 ${loan.loanNo} 已超过应还日期，请尽快跟进归还。`, dedupeKey: `loan-overdue:${loan.id}` }),
    )));
  }

  async list(user: AuthUser, query: { status?: LoanStatus; organizationId?: string; assigneeId?: string; mine?: boolean }) {
    this.requireInternal(user);
    if (query.status && !Object.values(LoanStatus).includes(query.status)) throw new BadRequestException('借出单状态无效');
    await this.fixOverdue();
    return this.prisma.loanOrder.findMany({
      where: {
        AND: [this.scopeWhere(user)],
        status: query.status,
        organizationId: query.organizationId,
        assigneeId: query.mine ? user.id : query.assigneeId,
      },
      include: loanInclude,
      orderBy: query.status === LoanStatus.QUEUED ? QUEUE_ORDER_BY : { updatedAt: 'desc' },
      take: 500,
    });
  }

  /** 列表筛选（搜索/状态/月份/回收站），供借测列表、总览统计与导出共用 */
  private buildWhere(user: AuthUser, query: Record<string, string>): Prisma.LoanOrderWhereInput {
    const today = businessDay(), weekEnd = new Date(+today + 7 * dayMs);
    const and: Prisma.LoanOrderWhereInput[] = [this.scopeWhere(user)];
    and.push(query.deleted === '1' ? { deletedAt: { not: null } } : { deletedAt: null });
    if (query.mine === '1') and.push({ assigneeId: user.id });
    switch (query.status) {
      case 'queued': and.push({ status: LoanStatus.QUEUED }); break;
      case 'ongoing': and.push({ status: { in: ACTIVE_STATUSES }, OR: [{ dueAt: null }, { dueAt: { gte: today } }] }); break;
      case 'overdue': and.push({ status: { in: ACTIVE_STATUSES }, dueAt: { lt: today } }); break;
      case 'due': and.push({ status: { in: ACTIVE_STATUSES }, dueAt: { gte: today, lte: weekEnd } }); break;
      case 'attention': and.push({ status: { in: ACTIVE_STATUSES }, dueAt: { lte: weekEnd } }); break;
      case 'active': and.push({ status: { in: ACTIVE_STATUSES } }); break;
      case 'stale': {
        // 久未跟进：进行中超 14 天无跟进记录
        const cutoff = new Date(+today - 14 * dayMs);
        and.push({ status: { in: ACTIVE_STATUSES }, createdAt: { lt: cutoff }, followUps: { none: { occurredAt: { gte: cutoff } } } });
        break;
      }
      case 'returned': and.push({ status: LoanStatus.RETURNED }); break;
      case 'cancelled': and.push({ status: LoanStatus.CANCELLED }); break;
    }
    const month = parseMonth(query.month ?? '');
    if (month) and.push(query.dateField === 'returned' ? { returnedAt: { gte: month.start, lt: month.end } } : { loanedAt: { gte: month.start, lt: month.end } });
    const search = (query.search ?? '').trim();
    if (search) and.push({ OR: [
      { loanNo: { contains: search, mode: 'insensitive' } },
      { organization: { name: { contains: search, mode: 'insensitive' } } },
      { contact: { name: { contains: search, mode: 'insensitive' } } },
      { contact: { phone: { contains: search, mode: 'insensitive' } } },
      { purpose: { contains: search, mode: 'insensitive' } },
      { note: { contains: search, mode: 'insensitive' } },
      { agreementNo: { contains: search, mode: 'insensitive' } },
      { outboundTracking: { contains: search, mode: 'insensitive' } },
      { returnTracking: { contains: search, mode: 'insensitive' } },
      { items: { some: { device: { OR: [
        { serialNumber: { contains: search, mode: 'insensitive' } },
        { cameraModel: { contains: search, mode: 'insensitive' } },
        { name: { contains: search, mode: 'insensitive' } },
      ] } } } },
      { followUps: { some: { content: { contains: search, mode: 'insensitive' } } } },
    ] });
    return { AND: and };
  }

  /** 列表展示字段：逾期动态推导（预计归还日早于业务日即逾期，不落库） */
  private decorate(row: { status: LoanStatus; dueAt: Date | null }) {
    const daysUntilDue = row.dueAt ? Math.round((+new Date(row.dueAt) - +businessDay()) / dayMs) : null;
    const active = ACTIVE_STATUSES.includes(row.status);
    return {
      daysUntilDue,
      overdueDays: active && daysUntilDue !== null && daysUntilDue < 0 ? -daysUntilDue : 0,
      effectiveStatus: active ? (daysUntilDue !== null && daysUntilDue < 0 ? LoanStatus.OVERDUE : LoanStatus.ONGOING) : row.status,
    };
  }

  /** 借测列表（新版）：全文搜索 + 状态/月份筛选 + 排序 + 服务端分页 */
  async listPage(user: AuthUser, query: Record<string, string>) {
    this.requireInternal(user);
    await this.fixOverdue();
    const page = Math.max(1, parseInt(query.page ?? '', 10) || 1);
    const pageSize = [20, 30, 50].includes(Number(query.pageSize)) ? Number(query.pageSize) : 20;
    const where = this.buildWhere(user, query);
    const orderBy: Prisma.LoanOrderOrderByWithRelationInput[] = query.status === 'queued' ? QUEUE_ORDER_BY
      : query.sort === 'due_soon' ? [{ dueAt: { sort: 'asc', nulls: 'last' } }, { id: 'asc' }]
        : [{ loanedAt: { sort: 'desc', nulls: 'last' } }, { updatedAt: 'desc' }, { id: 'asc' }];
    const [total, items] = await this.prisma.$transaction([
      this.prisma.loanOrder.count({ where }),
      this.prisma.loanOrder.findMany({ where, orderBy, skip: (page - 1) * pageSize, take: pageSize, include: loanInclude }),
    ]);
    return { total, items: items.map((row) => ({ ...row, ...this.decorate(row) })), page, pageSize };
  }

  /** 设备总览：统计卡片、待办、型号分布、平均借测天数、最近流转 */
  async dashboard(user: AuthUser) {
    this.requireInternal(user);
    await this.fixOverdue();
    const today = businessDay(), month = today.toISOString().slice(0, 7);
    const count = (q: Record<string, string>) => this.prisma.loanOrder.count({ where: this.buildWhere(user, q) });
    const [monthLoan, monthReturned, active, overdue, due, stale, queued] = await Promise.all([
      count({ month }), count({ month, dateField: 'returned', status: 'returned' }), count({ status: 'active' }),
      count({ status: 'overdue' }), count({ status: 'due' }), count({ status: 'stale' }), count({ status: 'queued' }),
    ]);
    const monthRange = parseMonth(month)!;
    const monthRepair = await this.prisma.repairOrder.count({
      where: { deletedAt: null, receivedAt: { gte: monthRange.start, lt: monthRange.end }, ...(user.role === 'employee' ? { OR: [{ createdById: user.id }, { assigneeId: user.id }] } : {}) },
    });
    const monthly = await this.prisma.loanOrder.findMany({
      where: this.buildWhere(user, { month }),
      select: { loanedAt: true, returnedAt: true, items: { select: { device: { select: { cameraModel: true } } }, take: 1 } },
    });
    const ranks = new Map<string, number>();
    for (const row of monthly) {
      const model = row.items[0]?.device.cameraModel || '未登记型号';
      ranks.set(model, (ranks.get(model) ?? 0) + 1);
    }
    const modelRank = [...ranks].map(([model, n]) => ({ model, count: n })).sort((a, b) => b.count - a.count).slice(0, 6);
    const durations = monthly.filter((r) => r.loanedAt && r.returnedAt && r.returnedAt >= r.loanedAt).map((r) => Math.round((+r.returnedAt! - +r.loanedAt!) / dayMs));
    const recentRows = await this.prisma.loanOrder.findMany({
      where: this.buildWhere(user, {}),
      include: loanInclude,
      orderBy: [{ loanedAt: { sort: 'desc', nulls: 'last' } }, { updatedAt: 'desc' }],
      take: 6,
    });
    const recentRepairs = await this.prisma.repairOrder.findMany({
      where: { deletedAt: null, ...(user.role === 'employee' ? { OR: [{ createdById: user.id }, { assigneeId: user.id }] } : {}) },
      select: {
        id: true, repairNo: true, status: true, createdAt: true, serialNumber: true,
        organization: { select: { name: true } },
        device: { select: { cameraModel: true, serialNumber: true } },
      },
      orderBy: { createdAt: 'desc' },
      take: 3,
    });
    return {
      counts: { monthLoan, monthRepair, monthReturned, active, overdue, due, stale, queued },
      modelRank,
      averageDays: durations.length ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : null,
      recent: [
        ...recentRows.map((row) => ({ kind: 'loan' as const, at: row.loanedAt ?? row.updatedAt, ...row, ...this.decorate(row) })),
        ...recentRepairs.map((row) => ({
          kind: 'repair' as const, at: row.createdAt, id: row.id, no: row.repairNo, status: row.status,
          organization: row.organization, model: row.device?.cameraModel ?? null, sn: row.serialNumber ?? row.device?.serialNumber ?? null,
        })),
      ],
      attention: (await this.listPage(user, { status: 'overdue', pageSize: '20' })).items.slice(0, 8),
      month, asOf: today.toISOString().slice(0, 10),
    };
  }

  /** 导出 Excel（三工作表：借测明细 / 跟进记录 / 统计），遵循当前筛选 */
  async buildExport(user: AuthUser, query: Record<string, string>) {
    this.requireInternal(user);
    await this.fixOverdue();
    const where = this.buildWhere(user, query);
    if (await this.prisma.loanOrder.count({ where }) > 10000) throw new BadRequestException('请缩小筛选范围至 10000 条以内');
    const rows = await this.prisma.loanOrder.findMany({ where, include: loanInclude, orderBy: [{ loanedAt: { sort: 'desc', nulls: 'last' } }] });
    const workbook = new ExcelJS.Workbook();
    const day = (d: Date | null) => (d ? d.toISOString().slice(0, 10) : '');
    const sheet = workbook.addWorksheet('借测明细');
    sheet.columns = [
      { header: '借测单号', key: 'loanNo', width: 18 }, { header: '客户', key: 'customer', width: 28 },
      { header: '联系人', key: 'contact', width: 12 }, { header: '联系电话', key: 'phone', width: 14 },
      { header: '跟进工程师', key: 'assignee', width: 12 }, { header: '设备型号', key: 'model', width: 12 },
      { header: '设备（SN）', key: 'devices', width: 36 }, { header: '借出日期', key: 'loanedAt', width: 12 },
      { header: '预计归还', key: 'dueAt', width: 12 }, { header: '实际归还', key: 'returnedAt', width: 12 },
      { header: '状态', key: 'status', width: 10 }, { header: '逾期天数', key: 'overdue', width: 10 },
      { header: '寄出物流', key: 'outbound', width: 20 }, { header: '归还物流', key: 'inbound', width: 20 },
      { header: '借测目的', key: 'purpose', width: 40 }, { header: '协议编号', key: 'agreementNo', width: 16 },
      { header: '最后跟进日期', key: 'lastFollowAt', width: 14 }, { header: '最后跟进人', key: 'lastFollowBy', width: 12 },
      { header: '最后跟进内容', key: 'lastFollow', width: 40 }, { header: '备注', key: 'note', width: 24 },
    ];
    const followSheet = workbook.addWorksheet('跟进记录');
    followSheet.columns = [
      { header: '借测单号', key: 'loanNo', width: 18 }, { header: '客户', key: 'customer', width: 28 },
      { header: '跟进日期', key: 'date', width: 12 }, { header: '跟进人', key: 'by', width: 12 },
      { header: '跟进内容', key: 'content', width: 60 },
    ];
    for (const row of rows) {
      const d = this.decorate(row), last = row.followUps[0];
      sheet.addRow({
        loanNo: row.loanNo, customer: row.organization.name,
        contact: row.contact?.name ?? '', phone: row.contact?.phone ?? '', assignee: row.assignee?.name ?? '',
        model: row.items[0]?.device.cameraModel ?? '', devices: row.items.map((item) => item.device.serialNumber || item.device.name).join('，'),
        loanedAt: day(row.loanedAt), dueAt: day(row.dueAt), returnedAt: day(row.returnedAt),
        status: LOAN_STATUS_LABELS[d.effectiveStatus], overdue: d.overdueDays || '',
        outbound: [row.outboundCarrier, row.outboundTracking].filter(Boolean).join(' '), inbound: [row.returnCarrier, row.returnTracking].filter(Boolean).join(' '),
        purpose: row.purpose, agreementNo: row.agreementNo ?? '',
        lastFollowAt: day(last?.occurredAt ?? null), lastFollowBy: last?.author.name ?? '', lastFollow: last?.content ?? '',
        note: row.note ?? '',
      });
      for (const f of row.followUps) followSheet.addRow({ loanNo: row.loanNo, customer: row.organization.name, date: day(f.occurredAt), by: f.author.name, content: f.content });
    }
    const active = rows.filter((r) => ACTIVE_STATUSES.includes(r.status));
    const stats = workbook.addWorksheet('统计');
    stats.columns = [{ header: '指标', key: 'k', width: 22 }, { header: '数值', key: 'v', width: 26 }];
    stats.addRows([
      { k: '导出记录数', v: rows.length }, { k: '当前借测中', v: active.length },
      { k: '已逾期', v: rows.filter((r) => this.decorate(r).overdueDays > 0).length },
      { k: '7天内到期', v: active.filter((r) => { const n = this.decorate(r).daysUntilDue; return n !== null && n >= 0 && n <= 7; }).length },
      { k: '已归还', v: rows.filter((r) => r.status === LoanStatus.RETURNED).length },
      { k: '排队中', v: rows.filter((r) => r.status === LoanStatus.QUEUED).length },
    ]);
    for (const s of [sheet, followSheet, stats]) {
      s.getRow(1).font = { bold: true };
      s.views = [{ state: 'frozen', ySplit: 1 }];
      s.autoFilter = { from: 'A1', to: { row: 1, column: s.columns.length } };
    }
    return Buffer.from(await workbook.xlsx.writeBuffer());
  }

  async get(user: AuthUser, id: string) {
    this.requireInternal(user);
    await this.fixOverdue();
    const loan = await this.prisma.loanOrder.findFirst({ where: { id, AND: [this.scopeWhere(user)] }, include: loanInclude });
    if (!loan) throw new NotFoundException('借出单不存在');
    return loan;
  }

  /** 当前启用的借测评分规则（供前端渲染评分表单） */
  async getScoreRule() {
    const rule = await this.prisma.loanScoreRule.findFirst({ where: { isActive: true }, orderBy: { createdAt: 'desc' } });
    if (!rule) throw new NotFoundException('尚未配置借测评分规则');
    return rule;
  }

  /** 入队登记：所有借测需求先入队，不要求设备与日期 */
  async create(user: AuthUser, dto: CreateLoanDto) {
    if (!await this.prisma.customerOrganization.findUnique({ where: { id: dto.organizationId }, select: { id: true } })) throw new BadRequestException('客户组织不存在');
    if (dto.contactId && !await this.prisma.contact.findFirst({ where: { id: dto.contactId, organizationId: dto.organizationId }, select: { id: true } })) throw new BadRequestException('联系人不属于该客户');
    if (dto.ticketId && !await this.prisma.ticket.findUnique({ where: { id: dto.ticketId }, select: { id: true } })) throw new BadRequestException('关联工单不存在');
    let loan;
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        const prefix = dateSerialPrefix('LN');
        const last = await this.prisma.loanOrder.findFirst({ where: { loanNo: { startsWith: prefix } }, orderBy: { loanNo: 'desc' }, select: { loanNo: true } });
        loan = await this.prisma.loanOrder.create({
          data: {
            loanNo: nextSerial(last?.loanNo ?? null, prefix),
            organizationId: dto.organizationId, contactId: dto.contactId || null, ticketId: dto.ticketId || null,
            createdById: user.id, purpose: dto.purpose,
            assessmentResult: dto.assessmentResult || null,
            score: dto.score ?? null, scoreDetail: dto.scoreDetail ? (dto.scoreDetail as Prisma.InputJsonValue) : undefined,
            scoreRuleVersion: dto.scoreDetail ? (await this.activeRuleVersion()) : null,
            agreementNo: dto.agreementNo || null, note: dto.note || null,
            infoComplete: Boolean(dto.score ?? dto.scoreDetail),
          },
          include: loanInclude,
        });
        break;
      }
      catch (error) { if ((error as { code?: string }).code !== 'P2002' || attempt === 3) throw error; }
    }
    return loan;
  }

  private async activeRuleVersion(): Promise<string | null> {
    const rule = await this.prisma.loanScoreRule.findFirst({ where: { isActive: true }, select: { version: true } });
    return rule?.version ?? null;
  }

  /** 完善评估信息：评分 / 评分明细 / 信息完整度 / 评估结论 */
  async score(user: AuthUser, id: string, dto: ScoreLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.QUEUED && loan.status !== LoanStatus.ONGOING) throw new BadRequestException('仅排队中或进行中的借测单可以评分');
    const detail = dto.scoreDetail ? (dto.scoreDetail as Prisma.InputJsonValue) : undefined;
    const derived = dto.score ?? (dto.scoreDetail ? Object.values(dto.scoreDetail).reduce((sum, v) => sum + (Number(v) || 0), 0) : undefined);
    return this.prisma.loanOrder.update({
      where: { id },
      data: {
        score: derived, scoreDetail: detail,
        scoreRuleVersion: dto.scoreDetail ? (loan.scoreRuleVersion ?? await this.activeRuleVersion()) : undefined,
        infoComplete: dto.infoComplete ?? (derived != null ? true : undefined),
        assessmentResult: dto.assessmentResult,
      },
      include: loanInclude,
    });
  }

  /** 手动提前：必须填写提前原因，留痕操作人 */
  async advance(user: AuthUser, id: string, dto: AdvanceLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.QUEUED) throw new BadRequestException('仅排队中的借测单可以提前');
    return this.prisma.loanOrder.update({
      where: { id },
      data: { advanceReason: dto.reason.trim(), advancedById: user.id, advancedAt: new Date() },
      include: loanInclude,
    });
  }

  /** 借出：排队单 → 进行中，校验设备并建立借用明细 */
  /** 手动登记的新样机：SN 已建档则关联校验，未建档自动创建公司样机 */
  private async resolveManualDevices(tx: Prisma.TransactionClient, manual: { serialNumber: string; cameraModel?: string }[], organizationId: string): Promise<string[]> {
    const normalized = [...new Map(manual.map((item) => [item.serialNumber.trim(), { serialNumber: item.serialNumber.trim(), cameraModel: item.cameraModel?.trim() || null }])).values()];
    const ids: string[] = [];
    for (const item of normalized) {
      let device = await tx.device.findUnique({ where: { serialNumber: item.serialNumber } });
      if (device && device.ownerType !== 'COMPANY') throw new BadRequestException(`SN ${item.serialNumber} 已登记为客户资产，不能作为公司样机借出`);
      if (device && device.status !== 'IN_STOCK') throw new BadRequestException(`SN ${item.serialNumber} 当前状态不可借出`);
      if (!device) {
        try {
          device = await tx.device.create({
            data: {
              name: item.cameraModel ? `${item.cameraModel} 样机` : '借测样机', serialNumber: item.serialNumber,
              cameraModel: item.cameraModel, ownerType: 'COMPANY', source: 'MANUAL', status: 'LOANED', organizationId,
              notes: '借出登记时手动建档',
            },
          });
        } catch (error) {
          if ((error as { code?: string }).code !== 'P2002') throw error;
          device = await tx.device.findUniqueOrThrow({ where: { serialNumber: item.serialNumber } });
          if (device.ownerType !== 'COMPANY' || device.status !== 'IN_STOCK') throw new BadRequestException(`SN ${item.serialNumber} 已被占用或当前不可借出`);
        }
      }
      ids.push(device.id);
    }
    return ids;
  }

  async ship(user: AuthUser, id: string, dto: ShipLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.QUEUED) throw new BadRequestException('仅排队中的借测单可以执行借出');
    const deviceIds = [...new Set(dto.deviceIds)];
    if (!deviceIds.length && !dto.manualDevices?.length) throw new BadRequestException('请选择或在下方手动登记至少一台设备');
    const dueAt = new Date(dto.dueAt);
    if (dueAt < new Date(dto.loanedAt)) throw new BadRequestException('预计归还日期不能早于借出日期');
    return this.prisma.$transaction(async (tx) => {
      const devices = await tx.device.findMany({ where: { id: { in: deviceIds } } });
      if (devices.length !== deviceIds.length) throw new BadRequestException('设备不存在');
      for (const device of devices) {
        if (device.ownerType !== 'COMPANY') throw new BadRequestException('客户资产不能创建借测单');
        if (device.status !== 'IN_STOCK') throw new BadRequestException(`设备 ${device.name}（${device.serialNumber ?? device.id}）当前不可借出`);
      }
      // 手动登记的 SN：已建档则并入校验，未建档自动创建公司样机（挂靠借测客户）
      const manualIds = dto.manualDevices?.length ? await this.resolveManualDevices(tx, dto.manualDevices, loan.organizationId) : [];
      const allIds = [...new Set([...deviceIds, ...manualIds])];
      const changed = await tx.loanOrder.updateMany({
        where: { id, status: LoanStatus.QUEUED },
        data: {
          status: LoanStatus.ONGOING, loanedAt: new Date(dto.loanedAt), dueAt,
          agreementNo: dto.agreementNo ?? loan.agreementNo,
          outboundCarrier: dto.outboundCarrier || null, outboundTracking: dto.outboundTracking || null,
        },
      });
      if (changed.count !== 1) throw new BadRequestException('借测单状态已变化，请刷新后重试');
      await tx.loanItem.createMany({ data: allIds.map((deviceId) => ({ loanOrderId: id, deviceId })) });
      // 公司样机临时挂靠到借测客户名下
      await tx.device.updateMany({ where: { id: { in: allIds } }, data: { status: 'LOANED', organizationId: loan.organizationId } });
      return tx.loanOrder.findUniqueOrThrow({ where: { id }, include: loanInclude });
    });
  }

  /** 跟进记录：写入借测跟进并同步到关联工单时间线（闭环） */
  async addFollowUp(user: AuthUser, id: string, dto: AddFollowUpDto) {
    const loan = await this.get(user, id);
    const occurredAt = dto.occurredAt ? new Date(dto.occurredAt) : new Date();
    const content = dto.content.trim();
    return this.prisma.$transaction(async (tx) => {
      const followUp = await tx.followUp.create({
        data: { loanOrderId: id, authorId: user.id, occurredAt, content },
        include: { author: { select: { id: true, name: true } } },
      });
      if (loan.ticketId) {
        await tx.ticketEvent.create({
          data: { ticketId: loan.ticketId, authorId: user.id, type: 'WORK_RECORD', visibility: 'INTERNAL', content: `【借测跟进 · ${loan.loanNo}】${content}` },
        });
      }
      return followUp;
    });
  }

  async update(user: AuthUser, id: string, dto: UpdateLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.QUEUED && loan.status !== LoanStatus.ONGOING && loan.status !== LoanStatus.OVERDUE) throw new BadRequestException('仅排队中或进行中的借出单可以修改');
    if (dto.organizationId && dto.organizationId !== loan.organizationId) throw new BadRequestException('客户不支持修改，请取消后重新建单');
    if (dto.contactId && !await this.prisma.contact.findFirst({ where: { id: dto.contactId, organizationId: loan.organizationId }, select: { id: true } })) throw new BadRequestException('联系人不属于该客户');
    if (dto.ticketId && !await this.prisma.ticket.findUnique({ where: { id: dto.ticketId }, select: { id: true } })) throw new BadRequestException('关联工单不存在');
    const detail = dto.scoreDetail ? (dto.scoreDetail as Prisma.InputJsonValue) : undefined;
    return this.prisma.loanOrder.update({
      where: { id },
      data: {
        purpose: dto.purpose, note: dto.note, agreementNo: dto.agreementNo,
        contactId: dto.contactId, ticketId: dto.ticketId,
        assessmentResult: dto.assessmentResult,
        score: dto.score, scoreDetail: detail,
        infoComplete: dto.score != null ? true : undefined,
        loanedAt: dto.loanedAt ? new Date(dto.loanedAt) : undefined,
        dueAt: dto.dueAt ? new Date(dto.dueAt) : undefined,
      },
      include: loanInclude,
    });
  }

  async assign(user: AuthUser, id: string, dto: AssignLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status === LoanStatus.RETURNED || loan.status === LoanStatus.CANCELLED) throw new BadRequestException('已结束的借出单不能指派');
    const assignee = await this.prisma.user.findFirst({ where: { id: dto.assigneeId, status: 'ACTIVE', role: { name: { in: ['admin', 'support', 'employee'] } } } });
    if (!assignee) throw new BadRequestException('被指派者不存在或不是内部成员');
    const updated = await this.prisma.loanOrder.update({ where: { id }, data: { assigneeId: dto.assigneeId }, include: loanInclude });
    await this.notifications.notify({ recipientId: dto.assigneeId, type: NOTIFICATION_TYPES.LOAN_ASSIGNED, title: '借出单已指派给你', body: `借出单 ${loan.loanNo} 已指派给你跟进。`, dedupeKey: `loan-assign:${loan.id}:${dto.assigneeId}` });
    return updated;
  }

  async returnItems(user: AuthUser, id: string, dto: ReturnLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.ONGOING && loan.status !== LoanStatus.OVERDUE) throw new BadRequestException('该借出单不在可归还状态');
    const notes = new Map((dto.items ?? []).map((item) => [item.deviceId, item.conditionNote]));
    return this.prisma.$transaction(async (tx) => {
      const now = new Date();
      for (const item of loan.items) {
        await tx.loanItem.update({ where: { id: item.id }, data: { returnedAt: item.returnedAt ?? now, conditionNote: notes.get(item.deviceId) ?? item.conditionNote } });
      }
      // 公司样机归还后回公司库存（解除临时挂靠）；客户资产不会出现在借测单中，防御性排除
      await tx.device.updateMany({ where: { id: { in: loan.items.map((item) => item.deviceId) }, ownerType: 'COMPANY' }, data: { status: 'IN_STOCK', organizationId: null } });
      return tx.loanOrder.update({ where: { id }, data: { status: LoanStatus.RETURNED, returnedAt: now }, include: loanInclude });
    });
  }

  async cancel(user: AuthUser, id: string) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.QUEUED && loan.status !== LoanStatus.ONGOING && loan.status !== LoanStatus.OVERDUE) throw new BadRequestException('该借出单不能取消');
    return this.prisma.$transaction(async (tx) => {
      await tx.device.updateMany({ where: { id: { in: loan.items.map((item) => item.deviceId) }, ownerType: 'COMPANY' }, data: { status: 'IN_STOCK', organizationId: null } });
      return tx.loanOrder.update({ where: { id }, data: { status: LoanStatus.CANCELLED }, include: loanInclude });
    });
  }
}
