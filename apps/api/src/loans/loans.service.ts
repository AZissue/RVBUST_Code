import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { LoanStatus, type Prisma } from '@prisma/client';
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

@Injectable()
export class LoansService {
  constructor(private readonly prisma: PrismaService, private readonly notifications: NotificationsService) {}

  private scopeWhere(user: AuthUser): Prisma.LoanOrderWhereInput {
    if (user.role === 'employee') return { OR: [{ assigneeId: user.id }, { createdById: user.id }] };
    return {};
  }

  private requireInternal(user: AuthUser) {
    if (user.role === 'customer') throw new BadRequestException('客户账号不能访问借还单');
  }

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
  async ship(user: AuthUser, id: string, dto: ShipLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.QUEUED) throw new BadRequestException('仅排队中的借测单可以执行借出');
    const deviceIds = [...new Set(dto.deviceIds)];
    const dueAt = new Date(dto.dueAt);
    if (dueAt < new Date(dto.loanedAt)) throw new BadRequestException('预计归还日期不能早于借出日期');
    return this.prisma.$transaction(async (tx) => {
      const devices = await tx.device.findMany({ where: { id: { in: deviceIds } } });
      if (devices.length !== deviceIds.length) throw new BadRequestException('设备不存在');
      for (const device of devices) {
        if (device.ownerType !== 'COMPANY') throw new BadRequestException('客户资产不能创建借测单');
        if (device.status !== 'IN_STOCK') throw new BadRequestException(`设备 ${device.name}（${device.serialNumber ?? device.id}）当前不可借出`);
      }
      const changed = await tx.loanOrder.updateMany({
        where: { id, status: LoanStatus.QUEUED },
        data: {
          status: LoanStatus.ONGOING, loanedAt: new Date(dto.loanedAt), dueAt,
          agreementNo: dto.agreementNo ?? loan.agreementNo,
          outboundCarrier: dto.outboundCarrier || null, outboundTracking: dto.outboundTracking || null,
        },
      });
      if (changed.count !== 1) throw new BadRequestException('借测单状态已变化，请刷新后重试');
      await tx.loanItem.createMany({ data: deviceIds.map((deviceId) => ({ loanOrderId: id, deviceId })) });
      // 公司样机临时挂靠到借测客户名下
      await tx.device.updateMany({ where: { id: { in: deviceIds } }, data: { status: 'LOANED', organizationId: loan.organizationId } });
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
