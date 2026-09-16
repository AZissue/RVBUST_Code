import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { LoanStatus, RepairStatus, TicketEventType, Visibility, type Prisma } from '@prisma/client';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { LinkageConfigService } from './linkage-config.service.js';
import { LinkageNotifyService } from './linkage-notify.service.js';
import {
  LINKAGE_EVENTS,
  type LoanFollowUpAddedPayload,
  type LoanInfoCompletedPayload,
  type LoanScoredPayload,
  type LoanStatusChangedPayload,
  type RepairFollowUpAddedPayload,
  type RepairStatusChangedPayload,
  type TicketCustomerReplyPayload,
} from './linkage.events.js';

// 回写工单时间线时的状态文案（与单据自身的状态名区分，如 ONGOING 回写为「已借出」）
const LOAN_SYNC_LABELS: Record<LoanStatus, string> = { QUEUED: '排队中', ONGOING: '已借出', OVERDUE: '已逾期', RETURNED: '已归还', CANCELLED: '已取消' };
const REPAIR_SYNC_LABELS: Record<RepairStatus, string> = { RECEIVED: '已受理', DIAGNOSING: '诊断中', REPAIRING: '维修中', SHIPPED: '已发货', CLOSED: '已关闭' };

const ACTIVE_LOAN_STATUSES: LoanStatus[] = [LoanStatus.QUEUED, LoanStatus.ONGOING, LoanStatus.OVERDUE];
const ACTIVE_REPAIR_STATUSES: RepairStatus[] = [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING, RepairStatus.SHIPPED];

const truncate = (text: string, max: number) => (text.length > max ? text.slice(0, max) : text);

/** 联动监听器：把子单动态回写为工单时间线（LINK_UPDATE），正向同步工单客户回复为子单 FollowUp，并发送联动通知 */
@Injectable()
export class LinkageListener {
  private readonly logger = new Logger(LinkageListener.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly linkageNotify: LinkageNotifyService,
    private readonly config: LinkageConfigService,
  ) {}

  private async writeTicketEvent(ticketId: string | null, authorId: string, content: string, metadata: Prisma.InputJsonValue) {
    if (!ticketId) return;
    try {
      await this.prisma.ticketEvent.create({
        data: { ticketId, authorId, type: TicketEventType.LINK_UPDATE, visibility: Visibility.INTERNAL, content, metadata },
      });
    } catch (error) {
      this.logger.error(`回写工单时间线失败（${content}）`, error instanceof Error ? error.stack : String(error));
    }
  }

  /** 子单全部完结时提醒工单负责人可以关单（仍有进行中子单则不发） */
  private async notifyIfAllCompleted(ticketId: string | null) {
    if (!ticketId) return;
    try {
      const [activeLoans, activeRepairs] = await Promise.all([
        this.prisma.loanOrder.count({ where: { ticketId, deletedAt: null, status: { in: ACTIVE_LOAN_STATUSES } } }),
        this.prisma.repairOrder.count({ where: { ticketId, deletedAt: null, status: { in: ACTIVE_REPAIR_STATUSES } } }),
      ]);
      if (activeLoans || activeRepairs) return;
      const ownerId = await this.linkageNotify.ticketOwnerId(ticketId);
      if (!ownerId) return;
      await this.linkageNotify.safeNotifyUnreadOnce({
        recipientId: ownerId, ticketId, type: NOTIFICATION_TYPES.LINK_ALL_COMPLETED,
        title: '工单关联业务已完结', body: '工单关联业务已完结，可标记解决并关闭工单',
        dedupeKey: `link-all-done:${ticketId}:${ownerId}`,
      });
    } catch (error) {
      this.logger.error(`子单完结提醒失败（工单 ${ticketId}）`, error instanceof Error ? error.stack : String(error));
    }
  }

  @OnEvent(LINKAGE_EVENTS.loanScored)
  async onLoanScored(payload: LoanScoredPayload) {
    const assessment = payload.assessmentResult?.trim() ? `，评估结论：${truncate(payload.assessmentResult.trim(), 100)}` : '';
    await this.writeTicketEvent(
      payload.ticketId, payload.actorId,
      `借测单 ${payload.loanNo} 评分 ${payload.score} 分${assessment}`,
      { linkType: 'loan', linkId: payload.loanId, linkNo: payload.loanNo, syncedFrom: 'linkage' },
    );
  }

  @OnEvent(LINKAGE_EVENTS.loanInfoCompleted)
  async onLoanInfoCompleted(payload: LoanInfoCompletedPayload) {
    await this.writeTicketEvent(
      payload.ticketId, payload.actorId,
      `借测单 ${payload.loanNo} 借测信息已完善`,
      { linkType: 'loan', linkId: payload.loanId, linkNo: payload.loanNo, syncedFrom: 'linkage' },
    );
  }

  @OnEvent(LINKAGE_EVENTS.loanStatusChanged)
  async onLoanStatusChanged(payload: LoanStatusChangedPayload) {
    await this.writeTicketEvent(
      payload.ticketId, payload.actorId,
      `借测单 ${payload.loanNo} ${LOAN_SYNC_LABELS[payload.to]}`,
      { linkType: 'loan', linkId: payload.loanId, linkNo: payload.loanNo, syncedFrom: 'linkage', from: payload.from, to: payload.to },
    );
    if (payload.to === LoanStatus.OVERDUE && payload.ticketId) {
      // 逾期通知受 linkage.notifyOnOverdue 开关控制
      const notifyOnOverdue = (await this.config.getAll()).notifyOnOverdue;
      if (!notifyOnOverdue) return;
      const ownerId = await this.linkageNotify.ticketOwnerId(payload.ticketId);
      if (!ownerId) return;
      await this.linkageNotify.safeNotifyUnreadOnce({
        recipientId: ownerId, ticketId: payload.ticketId, type: NOTIFICATION_TYPES.LINK_LOAN_OVERDUE, severity: 'WARNING',
        title: '借测单已逾期', body: `借测单 ${payload.loanNo} 已逾期，需联系客户（/loans/${payload.loanId}）。`,
        dedupeKey: `link-loan-overdue:${payload.loanId}:${ownerId}`,
      });
    }
    if (payload.to === LoanStatus.RETURNED || payload.to === LoanStatus.CANCELLED) await this.notifyIfAllCompleted(payload.ticketId);
  }

  @OnEvent(LINKAGE_EVENTS.loanFollowUpAdded)
  async onLoanFollowUpAdded(payload: LoanFollowUpAddedPayload) {
    // source=SYSTEM 是正向同步（工单客户回复）产生的跟进，回写即形成 A→B→A 回声，跳过
    if (payload.source === 'SYSTEM') return;
    await this.writeTicketEvent(
      payload.ticketId, payload.actorId,
      `借测单 ${payload.loanNo} 跟进：${truncate(payload.content, 100)}`,
      { linkType: 'loan', linkId: payload.loanId, linkNo: payload.loanNo, syncedFrom: 'linkage' },
    );
  }

  @OnEvent(LINKAGE_EVENTS.repairStatusChanged)
  async onRepairStatusChanged(payload: RepairStatusChangedPayload) {
    // 闭环事件：带处理结论时写明「已完结并返回客户 + 结论」，否则保持「已关闭」文案
    const label = payload.to === RepairStatus.CLOSED && payload.resolution?.trim()
      ? `已完结并返回客户，结论：${truncate(payload.resolution.trim(), 200)}`
      : REPAIR_SYNC_LABELS[payload.to];
    await this.writeTicketEvent(
      payload.ticketId, payload.actorId,
      `维修单 ${payload.repairNo} ${label}`,
      { linkType: 'repair', linkId: payload.repairId, linkNo: payload.repairNo, syncedFrom: 'linkage', from: payload.from, to: payload.to },
    );
    if (payload.to === RepairStatus.CLOSED) await this.notifyIfAllCompleted(payload.ticketId);
  }

  @OnEvent(LINKAGE_EVENTS.repairFollowUpAdded)
  async onRepairFollowUpAdded(payload: RepairFollowUpAddedPayload) {
    if (payload.source === 'SYSTEM') return;
    await this.writeTicketEvent(
      payload.ticketId, payload.actorId,
      `维修单 ${payload.repairNo} 跟进：${truncate(payload.content, 100)}`,
      { linkType: 'repair', linkId: payload.repairId, linkNo: payload.repairNo, syncedFrom: 'linkage' },
    );
  }

  @OnEvent(LINKAGE_EVENTS.ticketCustomerReply)
  async onTicketCustomerReply(payload: TicketCustomerReplyPayload) {
    try {
      const [loans, repairs] = await Promise.all([
        this.prisma.loanOrder.findMany({
          where: { ticketId: payload.ticketId, deletedAt: null, status: { in: [LoanStatus.QUEUED, LoanStatus.ONGOING, LoanStatus.OVERDUE] } },
          select: { id: true },
        }),
        this.prisma.repairOrder.findMany({
          where: { ticketId: payload.ticketId, deletedAt: null, status: { in: [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING, RepairStatus.SHIPPED] } },
          select: { id: true },
        }),
      ]);
      const data = [
        ...loans.map((loan) => ({ loanOrderId: loan.id, ticketId: payload.ticketId, authorId: payload.actorId, occurredAt: new Date(), content: `客户回复：${truncate(payload.content, 200)}`, source: 'SYSTEM' as const })),
        ...repairs.map((repair) => ({ repairOrderId: repair.id, ticketId: payload.ticketId, authorId: payload.actorId, occurredAt: new Date(), content: `客户回复：${truncate(payload.content, 200)}`, source: 'SYSTEM' as const })),
      ];
      // 只写子单 FollowUp，不再回写工单时间线（回声防护）
      if (data.length) await this.prisma.followUp.createMany({ data });
    } catch (error) {
      this.logger.error(`同步客户回复到子单跟进失败（工单 ${payload.ticketId}）`, error instanceof Error ? error.stack : String(error));
    }
  }
}
