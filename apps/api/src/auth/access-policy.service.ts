import { ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import type { Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service.js';
import type { AuthUser } from './auth.types.js';

@Injectable()
export class AccessPolicyService {
  constructor(private readonly prisma: PrismaService) {}

  customerWhere(user: AuthUser): Prisma.CustomerOrganizationWhereInput {
    if (user.role === 'customer') return { id: user.customerOrganizationId ?? '__none__' };
    return {};
  }

  ticketWhere(user: AuthUser): Prisma.TicketWhereInput {
    if (user.role === 'customer') return { organizationId: user.customerOrganizationId ?? '__none__' };
    if (user.role === 'employee') return { OR: [{ createdById: user.id }, { assigneeId: user.id }, { collaborators: { some: { userId: user.id } } }] };
    return {};
  }

  worklogWhere(user: AuthUser): Prisma.WorklogWhereInput {
    if (user.role === 'admin' || user.role === 'support') return {};
    return { authorId: user.id };
  }

  workItemWhere(user: AuthUser): Prisma.WorkItemWhereInput {
    if (user.role === 'admin' || user.role === 'support') return {};
    if (user.role === 'employee') return { OR: [{ ownerId: user.id }, { collaborators: { some: { userId: user.id } } }] };
    return { id: '__none__' };
  }

  async requireCustomer(user: AuthUser, organizationId: string) {
    const customer = await this.prisma.customerOrganization.findFirst({ where: { id: organizationId, ...this.customerWhere(user) } });
    if (!customer) throw new NotFoundException('客户不存在');
    return customer;
  }

  async requireTicket(user: AuthUser, ticketId: string) {
    const ticket = await this.prisma.ticket.findFirst({ where: { id: ticketId, AND: [this.ticketWhere(user)] } });
    if (!ticket) throw new NotFoundException('工单不存在');
    return ticket;
  }

  async requireWorkItem(user: AuthUser, workItemId: string) {
    const workItem = await this.prisma.workItem.findFirst({ where: { id: workItemId, AND: [this.workItemWhere(user)] } });
    if (!workItem) throw new NotFoundException('工作事项不存在');
    return workItem;
  }

  requireInternal(user: AuthUser) {
    if (user.role === 'customer') throw new ForbiddenException('客户账号不能访问内部数据');
  }
}
