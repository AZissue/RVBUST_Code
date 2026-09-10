import type { Prisma } from '@prisma/client';

export function ticketViewWhere(userId: string, view?: string, now = new Date()): Prisma.TicketWhereInput {
  const start = new Date(now); start.setHours(0, 0, 0, 0);
  const end = new Date(start); end.setDate(end.getDate() + 1);
  switch (view) {
    case 'assigned': return { assigneeId: userId };
    case 'collaborating': return { collaborators: { some: { userId } } };
    case 'invited': return { assistRequests: { some: { targetUserId: userId, status: 'PENDING' } } };
    case 'created': return { createdById: userId };
    case 'today-todo': return { assigneeId: userId, status: 'PENDING', OR: [{ plannedAt: null }, { plannedAt: { lt: end } }] };
    case 'today-done': return { assigneeId: userId, status: { in: ['RESOLVED', 'CLOSED'] }, resolvedAt: { gte: start, lt: end } };
    default: return {};
  }
}
