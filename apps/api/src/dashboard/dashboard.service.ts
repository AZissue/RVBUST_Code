import { BadRequestException, Injectable } from '@nestjs/common';
import { LoanStatus, RepairStatus, TicketStatus, WorkItemStatus, WorklogStatus } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { LinkageConfigService } from '../linkage/linkage-config.service.js';
import { PrismaService } from '../prisma/prisma.service.js';

// 进行中的单据状态集合（与 linkage / tickets 模块保持一致）
const ACTIVE_LOAN_STATUSES: LoanStatus[] = [LoanStatus.QUEUED, LoanStatus.ONGOING, LoanStatus.OVERDUE];
const ACTIVE_REPAIR_STATUSES: RepairStatus[] = [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING, RepairStatus.SHIPPED];

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;

const loanTodoSelect = {
  id: true, loanNo: true, ticketId: true, createdAt: true, dueAt: true,
  ticket: { select: { id: true, number: true, title: true } },
} as const;

@Injectable()
export class DashboardService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly access: AccessPolicyService,
    private readonly linkageConfig: LinkageConfigService,
  ) {}

  async summary(user: AuthUser) {
    const mine = { deletedAt: null, AND: [this.access.ticketWhere(user), { assigneeId: user.id }] };
    const unresolved = { ...mine, status: { notIn: [TicketStatus.RESOLVED, TicketStatus.CLOSED] } };
    const dayStart = new Date(); dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(dayStart); dayEnd.setDate(dayStart.getDate() + 1);
    const now = new Date();
    const staleBefore = new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000);
    const include = { organization: { select: { id: true, name: true } }, assignee: { select: { id: true, name: true } }, device: true };
    const [pending, inProgress, waitingCustomer, waitingRnd, highPriority, todayTodo, todayCompleted, myTickets, todayWorklogs, overdueLoanCount, repairingCount, staleTickets, overduePlanTickets, waitingTimeoutTickets] = await Promise.all([
      this.prisma.ticket.count({ where: { ...mine, status: 'PENDING' } }),
      this.prisma.ticket.count({ where: { ...mine, status: 'IN_PROGRESS' } }),
      this.prisma.ticket.count({ where: { ...mine, status: 'WAITING_CUSTOMER' } }),
      this.prisma.ticket.count({ where: { ...mine, status: 'WAITING_RND' } }),
      this.prisma.ticket.count({ where: { ...mine, priority: { in: ['HIGH', 'URGENT'] }, status: { notIn: ['RESOLVED', 'CLOSED'] } } }),
      this.prisma.ticket.count({ where: { ...mine, status: 'PENDING', OR: [{ plannedAt: null }, { plannedAt: { lt: dayEnd } }] } }),
      this.prisma.ticket.count({ where: { ...mine, status: { in: ['RESOLVED', 'CLOSED'] }, resolvedAt: { gte: dayStart, lt: dayEnd } } }),
      this.prisma.ticket.findMany({ where: unresolved, include, orderBy: [{ priority: 'desc' }, { updatedAt: 'desc' }], take: 6 }),
      this.prisma.worklog.findMany({ where: { authorId: user.id, status: 'CONFIRMED', occurredAt: { gte: dayStart, lt: dayEnd } }, include: { workType: true, organization: { select: { id: true, name: true } } }, orderBy: { occurredAt: 'desc' }, take: 10 }),
      // 我的借测逾期：直接按应还时间判断（不依赖惰性修正，ONGOING/OVERDUE 且 dueAt 已过均计入）
      this.prisma.loanOrder.count({ where: { assigneeId: user.id, status: { in: [LoanStatus.ONGOING, LoanStatus.OVERDUE] }, dueAt: { lt: now }, deletedAt: null } }),
      this.prisma.repairOrder.count({ where: { status: { in: [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING] }, deletedAt: null, ...(user.role === 'employee' ? { OR: [{ assigneeId: user.id }, { createdById: user.id }] } : {}) } }),
      // 需要关注：停滞超 3 天 / 计划逾期未兑现 / 等待反馈超时
      this.prisma.ticket.findMany({ where: { ...unresolved, updatedAt: { lt: staleBefore } }, include, orderBy: { updatedAt: 'asc' }, take: 5 }),
      this.prisma.ticket.findMany({ where: { ...unresolved, plannedAt: { lt: now } }, include, orderBy: { plannedAt: 'asc' }, take: 5 }),
      this.prisma.ticket.findMany({ where: { ...mine, status: { in: ['WAITING_CUSTOMER', 'WAITING_RND'] }, updatedAt: { lt: staleBefore } }, include, orderBy: { updatedAt: 'asc' }, take: 5 }),
    ]);
    const pendingAssistCount = await this.prisma.ticket.count({ where: { deletedAt: null, assistRequests: { some: { targetUserId: user.id, status: 'PENDING' } } } });
    return {
      pendingAssistCount,
      ticketCounts: { todayTodo, pending, inProgress, highPriority, waitingCustomer, waitingRnd, todayCompleted },
      myTickets,
      todayWorklogs,
      overdueLoanCount,
      repairingCount,
      alerts: { stale: staleTickets, overduePlan: overduePlanTickets, waitingTimeout: waitingTimeoutTickets },
    };
  }


  /** 当前用户负责的工单（报表日历用）：按创建时间（即工单时间）过滤，返回轻量字段 */
  async myTickets(user: AuthUser, fromRaw?: string, toRaw?: string) {
    this.access.requireInternal(user);
    const from = new Date(`${fromRaw ?? ''}T00:00:00`);
    const to = new Date(`${toRaw ?? ''}T00:00:00`);
    if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) throw new BadRequestException('日期格式无效，应为 YYYY-MM-DD');
    to.setDate(to.getDate() + 1);
    if (to <= from) throw new BadRequestException('结束日期不能早于开始日期');
    return this.prisma.ticket.findMany({
      where: { deletedAt: null, assigneeId: user.id, createdAt: { gte: from, lt: to } },
      select: { id: true, number: true, title: true, status: true, category: true, createdAt: true, resolvedAt: true, organization: { select: { id: true, name: true } } },
      orderBy: [{ createdAt: 'desc' }],
    });
  }

  /** 联动待办：当前用户相关的借测/维修联动四类待办（每组最多 5 条 + 总数） */
  async linkageTodos(user: AuthUser) {
    this.access.requireInternal(user);
    const cfg = await this.linkageConfig.getAll();
    const now = Date.now();
    // 借测三组待办归属：工单负责人或借测单创建人
    const loanOwnership = { OR: [{ ticket: { is: { assigneeId: user.id } } }, { createdById: user.id }] };
    // 维修停滞：最新 RepairEvent / FollowUp / 建单时间均早于超时阈值（无任何动态时以建单时间计）
    const stalledBefore = new Date(now - cfg.repairFollowupTimeoutHours * HOUR_MS);
    const stalledOwnership = { OR: [{ assigneeId: user.id }, ...(user.role === 'admin' ? [{ assigneeId: null }] : [])] };
    const stalledWhere = {
      status: { in: ACTIVE_REPAIR_STATUSES }, deletedAt: null, ...stalledOwnership,
      createdAt: { lt: stalledBefore },
      events: { none: { createdAt: { gte: stalledBefore } } },
      followUps: { none: { createdAt: { gte: stalledBefore } } },
    };
    const [infoItems, infoTotal, scoreItems, scoreTotal, stalledItems, stalledTotal, overdueItems, overdueTotal] = await Promise.all([
      this.prisma.loanOrder.findMany({
        where: { status: LoanStatus.QUEUED, infoComplete: false, deletedAt: null, ...loanOwnership },
        select: loanTodoSelect, orderBy: { createdAt: 'desc' }, take: 5,
      }),
      this.prisma.loanOrder.count({ where: { status: LoanStatus.QUEUED, infoComplete: false, deletedAt: null, ...loanOwnership } }),
      this.prisma.loanOrder.findMany({
        where: { status: LoanStatus.QUEUED, infoComplete: true, score: null, deletedAt: null, ...loanOwnership },
        select: loanTodoSelect, orderBy: { createdAt: 'desc' }, take: 5,
      }),
      this.prisma.loanOrder.count({ where: { status: LoanStatus.QUEUED, infoComplete: true, score: null, deletedAt: null, ...loanOwnership } }),
      this.prisma.repairOrder.findMany({
        where: stalledWhere,
        select: {
          id: true, repairNo: true, ticketId: true, createdAt: true,
          events: { select: { createdAt: true }, orderBy: { createdAt: 'desc' }, take: 1 },
          followUps: { select: { createdAt: true }, orderBy: { createdAt: 'desc' }, take: 1 },
          ticket: { select: { id: true, number: true, title: true } },
        },
        orderBy: { createdAt: 'desc' }, take: 5,
      }),
      this.prisma.repairOrder.count({ where: stalledWhere }),
      this.prisma.loanOrder.findMany({
        where: { status: LoanStatus.OVERDUE, deletedAt: null, ...loanOwnership },
        select: loanTodoSelect, orderBy: { createdAt: 'desc' }, take: 5,
      }),
      this.prisma.loanOrder.count({ where: { status: LoanStatus.OVERDUE, deletedAt: null, ...loanOwnership } }),
    ]);
    const loanTodo = (loan: (typeof infoItems)[number], pendingHours: number) => ({
      loanId: loan.id, loanNo: loan.loanNo, ticketId: loan.ticketId,
      ticketNumber: loan.ticket?.number ?? '', title: loan.ticket?.title ?? '',
      pendingHours,
    });
    return {
      infoIncomplete: {
        total: infoTotal,
        items: infoItems.map((loan) => loanTodo(loan, Math.floor((now - loan.createdAt.getTime()) / HOUR_MS))),
      },
      toScore: {
        total: scoreTotal,
        items: scoreItems.map((loan) => loanTodo(loan, Math.floor((now - loan.createdAt.getTime()) / HOUR_MS))),
      },
      repairsStalled: {
        total: stalledTotal,
        items: stalledItems.map((repair) => {
          const lastActivity = Math.max(
            repair.createdAt.getTime(),
            repair.events[0]?.createdAt.getTime() ?? 0,
            repair.followUps[0]?.createdAt.getTime() ?? 0,
          );
          return {
            repairId: repair.id, repairNo: repair.repairNo, ticketId: repair.ticketId,
            ticketNumber: repair.ticket?.number ?? '', title: repair.ticket?.title ?? '',
            stalledHours: Math.floor((now - lastActivity) / HOUR_MS),
          };
        }),
      },
      loansOverdue: {
        total: overdueTotal,
        items: overdueItems.map((loan) => ({
          loanId: loan.id, loanNo: loan.loanNo, ticketId: loan.ticketId,
          ticketNumber: loan.ticket?.number ?? '', title: loan.ticket?.title ?? '',
          overdueDays: Math.floor((now - (loan.dueAt ?? loan.createdAt).getTime()) / DAY_MS),
        })),
      },
    };
  }

  async reports(user: AuthUser) {
    this.access.requireInternal(user);
    const worklogScope = this.access.worklogWhere(user);
    const ticketScope = { deletedAt: null, AND: [this.access.ticketWhere(user)] };
    const workItemScope = this.access.workItemWhere(user);
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const weekStart = new Date(today); weekStart.setDate(today.getDate() - 6);
    const [weeklyLogs, supportedCustomers, ticketStatuses, totalItems, completedItems] = await this.prisma.$transaction([
      this.prisma.worklog.findMany({ where: { ...worklogScope, status: WorklogStatus.CONFIRMED, occurredAt: { gte: weekStart } }, select: { occurredAt: true, durationMinutes: true, organizationId: true, workType: { select: { label: true } } } }),
      this.prisma.worklog.findMany({ where: { ...worklogScope, status: WorklogStatus.CONFIRMED, occurredAt: { gte: weekStart }, organizationId: { not: null } }, distinct: ['organizationId'], select: { organizationId: true } }),
      this.prisma.ticket.findMany({ where: ticketScope, select: { status: true } }),
      this.prisma.workItem.count({ where: workItemScope }),
      this.prisma.workItem.count({ where: { ...workItemScope, status: WorkItemStatus.COMPLETED } }),
    ]);
    const typeCounts = new Map<string, number>();
    weeklyLogs.forEach((log) => typeCounts.set(log.workType.label, (typeCounts.get(log.workType.label) ?? 0) + 1));
    const statusCounts = new Map<TicketStatus, number>();
    ticketStatuses.forEach((ticket) => statusCounts.set(ticket.status, (statusCounts.get(ticket.status) ?? 0) + 1));
    const localDateKey = (value: Date) => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`;
    const daily = Array.from({ length: 7 }, (_, index) => {
      const day = new Date(weekStart); day.setDate(weekStart.getDate() + index);
      const key = localDateKey(day);
      const records = weeklyLogs.filter((log) => localDateKey(log.occurredAt) === key);
      return { date: key, count: records.length, minutes: records.reduce((sum, log) => sum + (log.durationMinutes ?? 0), 0) };
    });
    return {
      summary: { weeklyWorklogs: weeklyLogs.length, supportedCustomers: supportedCustomers.length, totalMinutes: weeklyLogs.reduce((sum, log) => sum + (log.durationMinutes ?? 0), 0), completionRate: totalItems ? Math.round(completedItems / totalItems * 100) : 0 },
      daily,
      workTypes: [...typeCounts].map(([label, count]) => ({ label, count })).sort((a, b) => b.count - a.count),
      ticketStatuses: [...statusCounts].map(([status, count]) => ({ status, count })),
    };
  }
}
