import { Injectable } from '@nestjs/common';
import { TicketEventType, TicketPriority, TicketStatus, WorkItemStatus, WorklogStatus } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';

@Injectable()
export class DashboardService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  async summary(user: AuthUser) {
    const ticketScope = this.access.ticketWhere(user);
    const workItemScope = this.access.workItemWhere(user);
    const now = new Date();
    const dayStart = new Date(now); dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(dayStart); dayEnd.setDate(dayEnd.getDate() + 1);
    const attentionEnd = new Date(now.getTime() + 24 * 60 * 60 * 1000);
    const mine = { AND: [ticketScope, { OR: [{ assigneeId: user.id }, { createdById: user.id }, { collaborators: { some: { userId: user.id } } }] }] };
    const internal = user.role !== 'customer';
    const [todayTodo, activeWorkItems, waitingFeedback, todayCompleted, pendingTickets, processingTickets, highPriority, waitingCustomer, waitingRnd, recentReplies, myTickets, myWorkItems, todayWorklogs] = await this.prisma.$transaction([
      this.prisma.workItem.count({ where: { ...workItemScope, status: WorkItemStatus.TODO, OR: [{ startDate: null }, { startDate: { lt: dayEnd } }] } }),
      this.prisma.workItem.count({ where: { ...workItemScope, status: WorkItemStatus.IN_PROGRESS } }),
      this.prisma.workItem.count({ where: { ...workItemScope, status: WorkItemStatus.WAITING_FEEDBACK } }),
      this.prisma.workItem.count({ where: { ...workItemScope, status: WorkItemStatus.COMPLETED, completedAt: { gte: dayStart, lt: dayEnd } } }),
      this.prisma.ticket.count({ where: { ...ticketScope, status: TicketStatus.PENDING } }),
      this.prisma.ticket.count({ where: { ...ticketScope, status: TicketStatus.IN_PROGRESS } }),
      this.prisma.ticket.count({ where: { ...ticketScope, priority: { in: [TicketPriority.HIGH, TicketPriority.URGENT] }, status: { notIn: [TicketStatus.RESOLVED, TicketStatus.CLOSED] } } }),
      this.prisma.ticket.count({ where: { ...ticketScope, status: TicketStatus.WAITING_CUSTOMER } }),
      this.prisma.ticket.count({ where: { ...ticketScope, status: TicketStatus.WAITING_RND } }),
      this.prisma.ticketEvent.findMany({ where: { type: TicketEventType.CUSTOMER_REPLY, ticket: ticketScope }, include: { ticket: { select: { id: true, number: true, title: true } }, author: { select: { name: true } } }, orderBy: { createdAt: 'desc' }, take: 5 }),
      this.prisma.ticket.findMany({ where: { AND: [mine, { status: { notIn: [TicketStatus.RESOLVED, TicketStatus.CLOSED] } }, { OR: [{ priority: { in: [TicketPriority.HIGH, TicketPriority.URGENT] } }, { status: { in: [TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND] } }, { plannedAt: { lte: attentionEnd } }, { assigneeId: user.id }] }] }, include: { organization: { select: { name: true } }, assignee: { select: { name: true } } }, orderBy: [{ priority: 'desc' }, { plannedAt: 'asc' }, { updatedAt: 'desc' }], take: 6 }),
      this.prisma.workItem.findMany({ where: { ...workItemScope, status: { in: [WorkItemStatus.IN_PROGRESS, WorkItemStatus.WAITING_FEEDBACK] } }, include: { workType: true, owner: { select: { id: true, name: true } }, organization: { select: { id: true, name: true } }, project: { select: { id: true, name: true } } }, orderBy: [{ dueDate: 'asc' }, { updatedAt: 'desc' }], take: 8 }),
      internal ? this.prisma.worklog.findMany({ where: { authorId: user.id, status: WorklogStatus.CONFIRMED, occurredAt: { gte: dayStart, lt: dayEnd } }, include: { workType: true, organization: { select: { id: true, name: true } }, ticket: { select: { id: true, number: true } }, workItem: { select: { id: true, title: true } } }, orderBy: { occurredAt: 'desc' }, take: 10 }) : this.prisma.worklog.findMany({ where: { id: '__none__' } }),
    ]);
    return {
      workItemCounts: { todayTodo, inProgress: activeWorkItems, waitingFeedback, todayCompleted },
      ticketCounts: { pending: pendingTickets, inProgress: processingTickets, highPriority, waitingCustomer, waitingRnd },
      recentReplies,
      myTickets,
      myWorkItems,
      todayWorklogs,
    };
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
