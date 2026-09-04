import { Injectable } from '@nestjs/common';
import { TicketStatus, WorkItemStatus, WorklogStatus } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';

@Injectable()
export class DashboardService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  async summary(user: AuthUser) {
    const mine = { AND: [this.access.ticketWhere(user), { assigneeId: user.id }] };
    const dayStart = new Date(); dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(dayStart); dayEnd.setDate(dayStart.getDate() + 1);
    const pending = await this.prisma.ticket.count({ where: { ...mine, status: 'PENDING' } });
    const inProgress = await this.prisma.ticket.count({ where: { ...mine, status: 'IN_PROGRESS' } });
    const waitingCustomer = await this.prisma.ticket.count({ where: { ...mine, status: 'WAITING_CUSTOMER' } });
    const waitingRnd = await this.prisma.ticket.count({ where: { ...mine, status: 'WAITING_RND' } });
    const highPriority = await this.prisma.ticket.count({ where: { ...mine, priority: { in: ['HIGH', 'URGENT'] }, status: { notIn: ['RESOLVED', 'CLOSED'] } } });
    const todayTodo = await this.prisma.ticket.count({ where: { ...mine, status: 'PENDING', OR: [{ plannedAt: null }, { plannedAt: { lt: dayEnd } }] } });
    const todayCompleted = await this.prisma.ticket.count({ where: { ...mine, status: { in: ['RESOLVED', 'CLOSED'] }, resolvedAt: { gte: dayStart, lt: dayEnd } } });
    const include = { organization: { select: { id: true, name: true } }, assignee: { select: { id: true, name: true } }, device: true };
    const activeTickets = await this.prisma.ticket.findMany({ where: { ...mine, status: 'IN_PROGRESS' }, include, orderBy: { updatedAt: 'desc' }, take: 8 });
    const myTickets = await this.prisma.ticket.findMany({ where: { ...mine, status: { notIn: ['RESOLVED', 'CLOSED'] } }, include, orderBy: [{ priority: 'desc' }, { updatedAt: 'desc' }], take: 6 });
    const todayWorklogs = user.role === 'customer' ? [] : await this.prisma.worklog.findMany({ where: { authorId: user.id, status: 'CONFIRMED', occurredAt: { gte: dayStart, lt: dayEnd } }, include: { workType: true, organization: { select: { id: true, name: true } } }, orderBy: { occurredAt: 'desc' }, take: 10 });
    return { ticketCounts: { todayTodo, pending, inProgress, highPriority, waitingCustomer, waitingRnd, todayCompleted }, myTickets, activeTickets, todayWorklogs };
  }


  async reports(user: AuthUser) {
    this.access.requireInternal(user);
    const worklogScope = this.access.worklogWhere(user);
    const ticketScope = this.access.ticketWhere(user);
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
