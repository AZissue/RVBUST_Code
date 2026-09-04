import { BadRequestException, ConflictException, ForbiddenException, Injectable } from '@nestjs/common';
import { TicketEventType, TicketStatus, Visibility, type Prisma } from '@prisma/client';
import { randomInt } from 'node:crypto';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { ChangeStatusDto } from './dto/change-status.dto.js';
import { CreateTicketEventDto } from './dto/ticket-event.dto.js';
import { CreateTicketDto, UpdateTicketDto } from './dto/ticket.dto.js';

const ticketInclude = {
  organization: { select: { id: true, name: true, level: true } },
  contact: true,
  device: true,
  project: true,
  assignee: { select: { id: true, name: true } },
  createdBy: { select: { id: true, name: true } },
  collaborators: { include: { user: { select: { id: true, name: true } } } },
} as const;

const transitions: Record<TicketStatus, TicketStatus[]> = {
  PENDING: [TicketStatus.IN_PROGRESS, TicketStatus.CLOSED],
  IN_PROGRESS: [TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  WAITING_CUSTOMER: [TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  WAITING_RND: [TicketStatus.IN_PROGRESS, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  RESOLVED: [TicketStatus.IN_PROGRESS, TicketStatus.CLOSED],
  CLOSED: [TicketStatus.IN_PROGRESS],
};

@Injectable()
export class TicketsService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  list(user: AuthUser, search?: string, status?: TicketStatus, mine = false) {
    if (status && !Object.values(TicketStatus).includes(status)) throw new BadRequestException('工单状态无效');
    return this.prisma.ticket.findMany({
      where: {
        AND: [this.access.ticketWhere(user), ...(mine ? [{ assigneeId: user.id }] : [])], status,
        ...(search ? { OR: [{ number: { contains: search, mode: 'insensitive' } }, { title: { contains: search, mode: 'insensitive' } }, { description: { contains: search, mode: 'insensitive' } }, { cameraModel: { contains: search, mode: 'insensitive' } }, { device: { name: { contains: search, mode: 'insensitive' } } }, { organization: { name: { contains: search, mode: 'insensitive' } } }] } : {}),
      },
      include: ticketInclude,
      omit: { rawText: user.role === 'customer', requestKey: true },
      orderBy: [{ priority: 'desc' }, { updatedAt: 'desc' }],
    });
  }

  async get(user: AuthUser, id: string) {
    await this.access.requireTicket(user, id);
    return this.prisma.ticket.findUnique({
      where: { id },
      omit: { rawText: user.role === 'customer', requestKey: true },
      include: {
        ...ticketInclude,
        events: {
          where: user.role === 'customer' ? { visibility: Visibility.CUSTOMER } : {},
          include: { author: { select: { id: true, name: true, role: { select: { name: true } } } }, attachments: true },
          orderBy: { createdAt: 'asc' },
        },
        attachments: { where: user.role === 'customer' ? { visibility: Visibility.CUSTOMER } : {} },
      },
    });
  }

  async create(user: AuthUser, dto: CreateTicketDto, db: Prisma.TransactionClient = this.prisma) {
    if (!dto.title.trim() || !dto.description.trim()) throw new BadRequestException('标题和问题描述不能为空');
    if (dto.requestKey) {
      const previous = await db.ticket.findUnique({ where: { requestKey: dto.requestKey }, include: ticketInclude });
      if (previous) {
        if (previous.createdById !== user.id) throw new ConflictException('提交标识已使用');
        return previous;
      }
    }
    const organizationId = user.role === 'customer' ? user.customerOrganizationId : dto.organizationId;
    if (!organizationId) throw new BadRequestException('客户账号未绑定客户公司');
    await this.access.requireCustomer(user, organizationId);
    await this.validateRelations(organizationId, dto);
    const collaboratorIds = user.role === 'customer' ? [] : [...new Set(dto.collaboratorIds ?? [])];
    const data: Prisma.TicketCreateInput = {
      number: this.generateNumber(), source: dto.source, category: dto.category, title: dto.title,
      rawText: dto.rawText, requestKey: dto.requestKey,
      description: dto.description, priority: dto.priority, cameraModel: dto.cameraModel,
      serialNumber: dto.serialNumber, sdkVersion: dto.sdkVersion, systemEnvironment: dto.systemEnvironment,
      plannedAt: dto.plannedAt ? new Date(dto.plannedAt) : undefined,
      organization: { connect: { id: organizationId } }, createdBy: { connect: { id: user.id } },
      contact: dto.contactId ? { connect: { id: dto.contactId } } : undefined,
      device: dto.deviceId ? { connect: { id: dto.deviceId } } : undefined,
      project: dto.projectId ? { connect: { id: dto.projectId } } : undefined,
      assignee: dto.assigneeId && user.role !== 'customer' ? { connect: { id: dto.assigneeId } } : undefined,
      collaborators: collaboratorIds.length ? { create: collaboratorIds.map((userId) => ({ user: { connect: { id: userId } } })) } : undefined,
      events: { create: { author: { connect: { id: user.id } }, type: TicketEventType.WORK_RECORD, visibility: user.role === 'customer' ? Visibility.CUSTOMER : Visibility.INTERNAL, content: '工单已创建' } },
    };
    for (let attempt = 0; attempt < 4; attempt++) {
      try { return await db.ticket.create({ data: { ...data, number: this.generateNumber() }, include: ticketInclude }); }
      catch (error) {
        if ((error as { code?: string }).code !== 'P2002' || attempt === 3) throw error;
        if (dto.requestKey) {
          const existing = await db.ticket.findUnique({ where: { requestKey: dto.requestKey }, include: ticketInclude });
          if (existing?.createdById === user.id) return existing;
          if (existing) throw new ConflictException('提交标识已使用');
        }
      }
    }
  }

  async update(user: AuthUser, id: string, dto: UpdateTicketDto) {
    if (user.role === 'customer') throw new ForbiddenException('客户账号不能修改工单内部字段');
    const current = await this.access.requireTicket(user, id);
    const organizationId = dto.organizationId ?? current.organizationId;
    await this.access.requireCustomer(user, organizationId);
    await this.validateRelations(organizationId, { ...dto, contactId: dto.contactId ?? current.contactId ?? undefined, deviceId: dto.deviceId ?? current.deviceId ?? undefined, projectId: dto.projectId ?? current.projectId ?? undefined });
    const collaboratorIds = dto.collaboratorIds ? [...new Set(dto.collaboratorIds)] : undefined;
    return this.prisma.ticket.update({
      where: { id },
      data: {
        source: dto.source, organizationId: dto.organizationId, contactId: dto.contactId,
        deviceId: dto.deviceId, projectId: dto.projectId, cameraModel: dto.cameraModel,
        serialNumber: dto.serialNumber, sdkVersion: dto.sdkVersion, systemEnvironment: dto.systemEnvironment,
        category: dto.category, title: dto.title, description: dto.description, priority: dto.priority,
        assigneeId: dto.assigneeId, plannedAt: dto.plannedAt ? new Date(dto.plannedAt) : undefined,
        events: dto.assigneeId && dto.assigneeId !== current.assigneeId ? { create: { authorId: user.id, type: TicketEventType.ASSIGNMENT, content: '负责人已变更', metadata: { from: current.assigneeId, to: dto.assigneeId } } } : undefined,
        collaborators: collaboratorIds ? { deleteMany: {}, create: collaboratorIds.map((userId) => ({ userId })) } : undefined,
      },
      include: ticketInclude,
    });
  }

  async changeStatus(user: AuthUser, id: string, dto: ChangeStatusDto) {
    if (user.role === 'customer') throw new ForbiddenException('客户账号不能修改工单状态');
    const ticket = await this.access.requireTicket(user, id);
    if (!transitions[ticket.status].includes(dto.status)) throw new BadRequestException(`不允许从 ${ticket.status} 变更为 ${dto.status}`);
    return this.prisma.$transaction(async (tx) => {
      const updated = await tx.ticket.update({
        where: { id }, data: { status: dto.status, resolvedAt: dto.status === TicketStatus.RESOLVED ? new Date() : dto.status === TicketStatus.IN_PROGRESS ? null : undefined },
        include: ticketInclude,
      });
      await tx.ticketEvent.create({
        data: { ticketId: id, authorId: user.id, type: TicketEventType.STATUS_CHANGE, visibility: Visibility.INTERNAL, content: `${ticket.status} -> ${dto.status}${dto.reason ? `：${dto.reason}` : ''}`, metadata: { from: ticket.status, to: dto.status } },
      });
      return updated;
    });
  }

  async addEvent(user: AuthUser, id: string, dto: CreateTicketEventDto) {
    await this.access.requireTicket(user, id);
    const isCustomer = user.role === 'customer';
    const visibility = isCustomer ? Visibility.CUSTOMER : (dto.visibility ?? Visibility.INTERNAL);
    const type = isCustomer ? TicketEventType.CUSTOMER_REPLY : dto.type;
    return this.prisma.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type, visibility, content: dto.content }, include: { author: { select: { id: true, name: true } } } });
  }

  async remove(id: string) {
    try { await this.prisma.ticket.delete({ where: { id } }); }
    catch (error) { if ((error as { code?: string }).code === 'P2003') throw new ConflictException('工单关联历史事项，不能删除追溯关系'); throw error; }
    return { success: true };
  }

  private async validateRelations(organizationId: string, dto: Partial<CreateTicketDto>) {
    const checks: Promise<unknown>[] = [];
    if (dto.assigneeId) {
      const assignee = await this.prisma.user.findFirst({ where: { id: dto.assigneeId, isActive: true, role: { name: { in: ['admin', 'support', 'employee'] } } } });
      if (!assignee) throw new BadRequestException('负责人不存在、已停用或不是内部成员');
    }
    if (dto.contactId) checks.push(this.prisma.contact.findFirstOrThrow({ where: { id: dto.contactId, organizationId } }));
    if (dto.deviceId) checks.push(this.prisma.device.findFirstOrThrow({ where: { id: dto.deviceId, organizationId } }));
    if (dto.projectId) checks.push(this.prisma.project.findFirstOrThrow({ where: { id: dto.projectId, organizationId } }));
    try { await Promise.all(checks); } catch { throw new BadRequestException('联系人、设备或项目不属于所选客户'); }
  }

  private generateNumber() {
    const date = new Date().toISOString().slice(2, 10).replaceAll('-', '');
    return `TS-${date}-${randomInt(0, 1_000_000).toString().padStart(6, '0')}`;
  }

  async convertWorkItem(user: AuthUser, id: string, organizationId: string) {
    this.access.requireInternal(user);
    const original = await this.access.requireWorkItem(user, id);
    if (user.role === 'employee' && original.ownerId !== user.id) throw new ForbiddenException('只有负责人可以转换事项');
    await this.access.requireCustomer(user, organizationId);
    if (original.organizationId && original.organizationId !== organizationId) throw new BadRequestException('不能更改历史事项的客户归属');
    return this.prisma.$transaction(async (tx) => {
      await tx.$queryRaw`SELECT id FROM work_items WHERE id = ${id}::uuid FOR UPDATE`;
      const item = await tx.workItem.findUniqueOrThrow({ where: { id }, include: { workType: true, collaborators: true, worklogs: true } });
      if (item.convertedTicketId) return tx.ticket.findUniqueOrThrow({ where: { id: item.convertedTicketId }, include: ticketInclude });
      if (item.worklogs.some((log) => log.ticketId || (log.organizationId && log.organizationId !== organizationId))) throw new ConflictException('关联记录已有工单或客户冲突，请先整理后转换');
      const created = await this.create(user, { source: 'OTHER', organizationId, projectId: item.projectId ?? undefined, title: item.title.length >= 3 ? item.title : `事项：${item.title}`, description: item.description || item.title.padEnd(3, ' '), category: item.workType.label, assigneeId: item.ownerId, priority: item.priority, plannedAt: item.dueDate?.toISOString(), collaboratorIds: item.collaborators.map((c) => c.userId) }, tx);
      if (!created) throw new BadRequestException('转换失败');
      const status: TicketStatus = ({ TODO: 'PENDING', IN_PROGRESS: 'IN_PROGRESS', WAITING_FEEDBACK: 'WAITING_CUSTOMER', COMPLETED: 'RESOLVED', CANCELED: 'CLOSED' } as const)[item.status];
      await tx.ticket.update({ where: { id: created.id }, data: { status, resolvedAt: item.completedAt } });
      await tx.ticketEvent.create({ data: { ticketId: created.id, authorId: user.id, type: 'INTERNAL_NOTE', content: '由历史工作事项确认转换，原始数据保留', metadata: { workItemId: id, originalStatus: item.status, originalProgress: item.progress, originalCreatedAt: item.createdAt.toISOString(), tags: item.tags } } });
      await tx.workItem.update({ where: { id }, data: { convertedTicketId: created.id } });
      await tx.worklog.updateMany({ where: { workItemId: id, ticketId: null }, data: { ticketId: created.id, organizationId } });
      return tx.ticket.findUniqueOrThrow({ where: { id: created.id }, include: ticketInclude });
    });
  }
}
