import { Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import { LoanStatus, RepairStatus, TicketEventType, Visibility, type Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service.js';
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

const truncate = (text: string, max: number) => (text.length > max ? text.slice(0, max) : text);

/** 联动监听器：把子单动态回写为工单时间线（LINK_UPDATE），并把工单客户回复正向同步为子单 FollowUp */
@Injectable()
export class LinkageListener {
  private readonly logger = new Logger(LinkageListener.name);

  constructor(private readonly prisma: PrismaService) {}

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
    await this.writeTicketEvent(
      payload.ticketId, payload.actorId,
      `维修单 ${payload.repairNo} ${REPAIR_SYNC_LABELS[payload.to]}`,
      { linkType: 'repair', linkId: payload.repairId, linkNo: payload.repairNo, syncedFrom: 'linkage', from: payload.from, to: payload.to },
    );
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
