import type { FollowUpSource, LoanStatus, RepairStatus } from '@prisma/client';

/**
 * 工单 ↔ 借测/维修联动领域事件。
 * loans/repairs/tickets 各 service 只负责 emit，不互相引用、不直写对方时间线；
 * linkage 监听器统一消费并回写（反向：子单动态 → 工单 TicketEvent；正向：工单客户回复 → 子单 FollowUp）。
 */
export const LINKAGE_EVENTS = {
  loanScored: 'loan.scored',
  loanInfoCompleted: 'loan.infoCompleted',
  loanStatusChanged: 'loan.statusChanged',
  loanFollowUpAdded: 'loan.followUpAdded',
  repairStatusChanged: 'repair.statusChanged',
  repairFollowUpAdded: 'repair.followUpAdded',
  ticketCustomerReply: 'ticket.customerReply',
} as const;

interface LoanEventBase {
  loanId: string;
  loanNo: string;
  ticketId: string | null;
  actorId: string;
}

export interface LoanScoredPayload extends LoanEventBase {
  score: number;
  assessmentResult: string | null;
}

export interface LoanInfoCompletedPayload extends LoanEventBase {}

export interface LoanStatusChangedPayload extends LoanEventBase {
  from: LoanStatus;
  to: LoanStatus;
}

export interface LoanFollowUpAddedPayload extends LoanEventBase {
  content: string;
  source: FollowUpSource;
}

interface RepairEventBase {
  repairId: string;
  repairNo: string;
  ticketId: string | null;
  actorId: string;
}

export interface RepairStatusChangedPayload extends RepairEventBase {
  from: RepairStatus;
  to: RepairStatus;
  /** 完结（CLOSED）时的处理结论，由 repairs.transition 透传，供闭环文案与通知使用 */
  resolution?: string | null;
}

export interface RepairFollowUpAddedPayload extends RepairEventBase {
  content: string;
  source: FollowUpSource;
}

/** 工单客户回复（正向同步源；监听端只生成 source=SYSTEM 的 FollowUp，不再回写工单，避免回声） */
export interface TicketCustomerReplyPayload {
  ticketId: string;
  actorId: string;
  content: string;
}
