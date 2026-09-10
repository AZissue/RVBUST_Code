import { Injectable } from '@nestjs/common';
import { LoanStatus, RepairStatus, TicketStatus, WorkItemStatus, WorklogStatus } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';

@Injectable()
export class DashboardService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  async summary(user: AuthUser) {
    const mine = { deletedAt: null, AND: [this.access.ticketWhere(user), { assigneeId: user.id }] };
    const unresolved = { ...mine, status: { notIn: [TicketStatus.RESOLVED, TicketStatus.CLOSED] } };
    const dayStart = new Date(); dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(dayStart); dayEnd.setDate(dayStart.getDate() + 1);
    const now = new Date();
    const staleBefore = new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000);
    const include = { organization: { select: { id: true, name: true } }, assignee: { select: { id: true, name: true } }, device: true };
    const isCustomer = user.role === 'customer';
    const [pending, inProgress, waitingCustomer, waitingRnd, highPriority, todayTodo, todayCompleted, myTickets, todayWorklogs, overdueLoanCount, repairingCount, staleTickets, overduePlanTickets, waitingTimeoutTickets] = await Promise.all([
      this.prisma.ticket.count({ where: { ...mine, status: 'PENDING' } }),
      this.prisma.ticket.count({ where: { ...mine, status: 'IN_PROGRESS' } }),
      this.prisma.ticket.count({ where: { ...mine, status: 'WAITING_CUSTOMER' } }),
      this.prisma.ticket.count({ where: { ...mine, status: 'WAITING_RND' } }),
      this.prisma.ticket.count({ where: { ...mine, priority: { in: ['HIGH', 'URGENT'] }, status: { notIn: ['RESOLVED', 'CLOSED'] } } }),
      this.prisma.ticket.count({ where: { ...mine, status: 'PENDING', OR: [{ plannedAt: null }, { plannedAt: { lt: dayEnd } }] } }),
      this.prisma.ticket.count({ where: { ...mine, status: { in: ['RESOLVED', 'CLOSED'] }, resolvedAt: { gte: dayStart, lt: dayEnd } } }),
      this.prisma.ticket.findMany({ where: unresolved, include, orderBy: [{ priority: 'desc' }, { updatedAt: 'desc' }], take: 6 }),
      isCustomer ? Promise.resolve([]) : this.prisma.worklog.findMany({ where: { authorId: user.id, status: 'CONFIRMED', occurredAt: { gte: dayStart, lt: dayEnd } }, include: { workType: true, organization: { select: { id: true, name: true } } }, orderBy: { occurredAt: 'desc' }, take: 10 }),
      // 我的借测逾期：直接按应还时间判断（不依赖惰性修正，ONGOING/OVERDUE 且 dueAt 已过均计入）
      isCustomer ? Promise.resolve(0) : this.prisma.loanOrder.count({ where: { assigneeId: user.id, status: { in: [LoanStatus.ONGOING, LoanStatus.OVERDUE] }, dueAt: { lt: now } } }),
      isCustomer ? Promise.resolve(0) : this.prisma.repairOrder.count({ where: { status: { in: [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING] }, ...(user.role === 'employee' ? { OR: [{ assigneeId: user.id }, { createdById: user.id }] } : {}) } }),
      // 需要关注：停滞超 3 天 / 计划逾期未兑现 / 等待反馈超时
      this.prisma.ticket.findMany({ where: { ...unresolved, updatedAt: { lt: staleBefore } }, include, orderBy: { updatedAt: 'asc' }, take: 5 }),
      this.prisma.ticket.findMany({ where: { ...unresolved, plannedAt: { lt: now } }, include, orderBy: { plannedAt: 'asc' }, take: 5 }),
      this.prisma.ticket.findMany({ where: { ...mine, status: { in: ['WAITING_CUSTOMER', 'WAITING_RND'] }, updatedAt: { lt: staleBefore } }, include, orderBy: { updatedAt: 'asc' }, take: 5 }),
    ]);
    const pendingAssistCount = isCustomer ? 0 : await this.prisma.ticket.count({ where: { deletedAt: null, assistRequests: { some: { targetUserId: user.id, status: 'PENDING' } } } });
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
