import { Injectable } from '@nestjs/common';
import { LoanStatus, RepairStatus, TicketEventType, Visibility } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { LoansService } from '../loans/loans.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { RepairsService } from '../repairs/repairs.service.js';

// 进行中的单据状态集合（与迁移里的部分唯一索引一致）：同工单仅允许一张进行中同类单据
const ACTIVE_LOAN_STATUSES: LoanStatus[] = [LoanStatus.QUEUED, LoanStatus.ONGOING, LoanStatus.OVERDUE];
const ACTIVE_REPAIR_STATUSES: RepairStatus[] = [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING, RepairStatus.SHIPPED];

const isP2002 = (error: unknown) => (error as { code?: string }).code === 'P2002';

@Injectable()
export class LinkageService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly loans: LoansService,
    private readonly repairs: RepairsService,
    private readonly access: AccessPolicyService,
  ) {}

  /** 从工单创建借测单（幂等）：已有进行中借测单直接返回，不重复创建 */
  async createLoanFromTicket(user: AuthUser, ticketId: string) {
    const ticket = await this.access.requireTicket(user, ticketId);
    const existing = await this.prisma.loanOrder.findFirst({ where: { ticketId, status: { in: ACTIVE_LOAN_STATUSES }, deletedAt: null }, orderBy: { createdAt: 'desc' } });
    if (existing) return { loan: existing, created: false };
    let loan: { id: string; loanNo: string; status: LoanStatus };
    try {
      loan = (await this.loans.create(user, {
        organizationId: ticket.organizationId,
        contactId: ticket.contactId ?? undefined,
        ticketId,
        purpose: ticket.description.slice(0, 200),
      }))!;
    } catch (error) {
      // 并发兜底：唯一索引冲突时返回已存在的进行中借测单
      if (!isP2002(error)) throw error;
      loan = await this.prisma.loanOrder.findFirstOrThrow({ where: { ticketId, status: { in: ACTIVE_LOAN_STATUSES }, deletedAt: null }, orderBy: { createdAt: 'desc' } });
      return { loan, created: false };
    }
    await this.prisma.ticketEvent.create({
      data: {
        ticketId, authorId: user.id, type: TicketEventType.LINK_CREATED, visibility: Visibility.INTERNAL,
        content: `已创建借测单 ${loan.loanNo}（排队中），待完善借测信息`,
        metadata: { linkType: 'loan', linkId: loan.id, linkNo: loan.loanNo },
      },
    });
    return { loan, created: true };
  }

  /** 从工单创建维修单（幂等）：已有进行中维修单直接返回，不重复创建 */
  async createRepairFromTicket(user: AuthUser, ticketId: string) {
    const ticket = await this.access.requireTicket(user, ticketId);
    const existing = await this.prisma.repairOrder.findFirst({ where: { ticketId, status: { in: ACTIVE_REPAIR_STATUSES }, deletedAt: null }, orderBy: { createdAt: 'desc' } });
    if (existing) return { repair: existing, created: false };
    let repair: { id: string; repairNo: string; status: RepairStatus };
    try {
      repair = (await this.repairs.create(user, {
        organizationId: ticket.organizationId,
        contactId: ticket.contactId ?? undefined,
        deviceId: ticket.deviceId ?? undefined,
        serialNumber: ticket.serialNumber ?? undefined,
        ticketId,
        symptom: ticket.description,
        receivedAt: new Date().toISOString(),
      }))!;
    } catch (error) {
      if (!isP2002(error)) throw error;
      repair = await this.prisma.repairOrder.findFirstOrThrow({ where: { ticketId, status: { in: ACTIVE_REPAIR_STATUSES }, deletedAt: null }, orderBy: { createdAt: 'desc' } });
      return { repair, created: false };
    }
    await this.prisma.ticketEvent.create({
      data: {
        ticketId, authorId: user.id, type: TicketEventType.LINK_CREATED, visibility: Visibility.INTERNAL,
        content: `已创建维修单 ${repair.repairNo}（已受理）`,
        metadata: { linkType: 'repair', linkId: repair.id, linkNo: repair.repairNo },
      },
    });
    return { repair, created: true };
  }

  /** 工单已关联的借测单/维修单列表（创建时间倒序），供联动卡片展示 */
  async listLinks(user: AuthUser, ticketId: string) {
    await this.access.requireTicket(user, ticketId);
    const [loans, repairs] = await Promise.all([
      this.prisma.loanOrder.findMany({
        where: { ticketId, deletedAt: null },
        select: { id: true, loanNo: true, status: true, infoComplete: true, createdAt: true, assignee: { select: { id: true, name: true } } },
        orderBy: { createdAt: 'desc' },
      }),
      this.prisma.repairOrder.findMany({
        where: { ticketId, deletedAt: null },
        select: { id: true, repairNo: true, status: true, createdAt: true, assignee: { select: { id: true, name: true } } },
        orderBy: { createdAt: 'desc' },
      }),
    ]);
    return { loans, repairs };
  }
}
