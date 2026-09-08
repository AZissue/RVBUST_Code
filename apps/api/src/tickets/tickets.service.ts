import { BadRequestException, ConflictException, ForbiddenException, Injectable } from '@nestjs/common';
import { TicketEventType, TicketStatus, Visibility, type Prisma } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { NotificationsService } from '../notifications/notifications.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { ChangeStatusDto } from './dto/change-status.dto.js';
import { zhStatus } from '../common/status-labels.js';
import { CreateTicketEventDto } from './dto/ticket-event.dto.js';
import { CreateTicketDto, UpdateTicketDto, ChangeCreatorDto } from './dto/ticket.dto.js';
import { ticketCategoryFromLabel } from '../common/ticket-categories.js';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';

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
  PENDING: [TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  IN_PROGRESS: [TicketStatus.PENDING, TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  WAITING_CUSTOMER: [TicketStatus.PENDING, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_RND, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  WAITING_RND: [TicketStatus.PENDING, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  RESOLVED: [TicketStatus.PENDING, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.CLOSED],
  CLOSED: [TicketStatus.PENDING, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.RESOLVED],
};

@Injectable()
export class TicketsService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService, private readonly notifications: NotificationsService) {}

  private notifyAssignee(ticketId: string, number: string, assigneeId: string) {
    return this.notifications.notify({
      recipientId: assigneeId, ticketId, type: NOTIFICATION_TYPES.TICKET_ASSIGNED, title: '工单已指派给你',
      body: `工单 ${number} 已指派给你处理。`, dedupeKey: `ticket-assign:${ticketId}:${assigneeId}`,
    });
  }

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
    const assigneeId = user.role === 'customer' ? undefined : (dto.assigneeId ?? user.id);
    const data: Omit<Prisma.TicketCreateInput, 'number'> = {
      category: dto.category, title: dto.title,
      rawText: dto.rawText, requestKey: dto.requestKey,
      description: dto.description, priority: dto.priority, cameraModel: dto.cameraModel,
      serialNumber: dto.serialNumber, sdkVersion: dto.sdkVersion, systemEnvironment: dto.systemEnvironment,
      plannedAt: dto.plannedAt ? new Date(dto.plannedAt) : undefined,
      organization: { connect: { id: organizationId } }, createdBy: { connect: { id: user.id } },
      contact: dto.contactId ? { connect: { id: dto.contactId } } : undefined,
      device: dto.deviceId ? { connect: { id: dto.deviceId } } : undefined,
      project: dto.projectId ? { connect: { id: dto.projectId } } : undefined,
      assignee: assigneeId ? { connect: { id: assigneeId } } : undefined,
      collaborators: collaboratorIds.length ? { create: collaboratorIds.map((userId) => ({ user: { connect: { id: userId } } })) } : undefined,
      events: { create: { author: { connect: { id: user.id } }, type: TicketEventType.WORK_RECORD, visibility: user.role === 'customer' ? Visibility.CUSTOMER : Visibility.INTERNAL, content: '工单已创建' } },
    };
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        const created = await db.ticket.create({ data: { ...data, number: await this.generateNumber(db) }, include: ticketInclude });
        // 事务内调用（如事项转换）跳过通知，由外层在事务提交后补发，避免引用未提交工单
        if (db === this.prisma && assigneeId && assigneeId !== user.id) await this.notifyAssignee(created.id, created.number, assigneeId);
        return created;
      }
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
    if (!this.access.canEditTicket(user, current)) throw new ForbiddenException('仅创建人、负责人或管理员可以更新该工单');
    if (dto.assigneeId && dto.assigneeId !== current.assigneeId && user.role !== 'admin' && current.assigneeId !== user.id) throw new ForbiddenException('仅当前负责人或管理员可以转交工单');
    const organizationId = dto.organizationId ?? current.organizationId;
    await this.access.requireCustomer(user, organizationId);
    await this.validateRelations(organizationId, { ...dto, contactId: dto.contactId ?? current.contactId ?? undefined, deviceId: dto.deviceId ?? current.deviceId ?? undefined, projectId: dto.projectId ?? current.projectId ?? undefined });
    const collaboratorIds = dto.collaboratorIds ? [...new Set(dto.collaboratorIds)] : undefined;
    const updated = await this.prisma.ticket.update({
      where: { id },
      data: {
        organizationId: dto.organizationId, contactId: dto.contactId,
        deviceId: dto.deviceId, projectId: dto.projectId, cameraModel: dto.cameraModel,
        serialNumber: dto.serialNumber, sdkVersion: dto.sdkVersion, systemEnvironment: dto.systemEnvironment,
        category: dto.category, title: dto.title, description: dto.description, priority: dto.priority,
        assigneeId: dto.assigneeId, plannedAt: dto.plannedAt ? new Date(dto.plannedAt) : undefined,
        events: dto.assigneeId && dto.assigneeId !== current.assigneeId ? { create: { authorId: user.id, type: TicketEventType.ASSIGNMENT, content: '负责人已变更', metadata: { from: current.assigneeId, to: dto.assigneeId } } } : undefined,
        collaborators: collaboratorIds ? { deleteMany: {}, create: collaboratorIds.map((userId) => ({ userId })) } : undefined,
      },
      include: ticketInclude,
    });
    if (dto.assigneeId && dto.assigneeId !== current.assigneeId) await this.notifyAssignee(id, updated.number, dto.assigneeId);
    return updated;
  }

  async changeStatus(user: AuthUser, id: string, dto: ChangeStatusDto) {
    if (user.role === 'customer') throw new ForbiddenException('客户账号不能修改工单状态');
    const ticket = await this.access.requireTicket(user, id);
    if (user.role !== 'admin' && ticket.assigneeId !== user.id) throw new ForbiddenException('仅当前负责人或管理员可以变更工单状态');
    if (!transitions[ticket.status].includes(dto.status)) throw new BadRequestException(`不允许从「${zhStatus(ticket.status)}」变更为「${zhStatus(dto.status)}」`);
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
    const ticket = await this.access.requireTicket(user, id);
    // 内部备注（排查过程）允许所有内部成员在任何工单下追加，便于协作排查；
    // 客户可见回复及其他类型的写入仍仅限创建人、负责人或管理员。
    const isInternalNote = user.role !== 'customer' && dto.type === TicketEventType.INTERNAL_NOTE;
    if (user.role !== 'customer' && !isInternalNote && !this.access.canEditTicket(user, ticket)) throw new ForbiddenException('仅创建人、负责人或管理员可以更新该工单');
    const isCustomer = user.role === 'customer';
    const type = isCustomer ? TicketEventType.CUSTOMER_REPLY : dto.type;
    const visibility = isCustomer ? Visibility.CUSTOMER : type === TicketEventType.INTERNAL_NOTE ? Visibility.INTERNAL : (dto.visibility ?? Visibility.INTERNAL);
    return this.prisma.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type, visibility, content: dto.content }, include: { author: { select: { id: true, name: true } } } });
  }

  async changeCreator(user: AuthUser, id: string, dto: ChangeCreatorDto) {
    const current = await this.access.requireTicket(user, id);
    const target = await this.prisma.user.findFirst({ where: { id: dto.createdById, status: 'ACTIVE', role: { name: { in: ['admin', 'support', 'employee'] } } }, select: { id: true, name: true } });
    if (!target) throw new BadRequestException('目标用户不存在、已停用或不是内部成员');
    if (target.id === current.createdById) return this.prisma.ticket.findUniqueOrThrow({ where: { id }, include: ticketInclude });
    const from = await this.prisma.user.findUniqueOrThrow({ where: { id: current.createdById }, select: { name: true } });
    return this.prisma.$transaction(async (tx) => {
      await tx.ticket.update({ where: { id }, data: { createdById: target.id } });
      await tx.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type: TicketEventType.INTERNAL_NOTE, visibility: Visibility.INTERNAL, content: `创建人由「${from.name}」变更为「${target.name}」`, metadata: { from: current.createdById, to: target.id } } });
      return tx.ticket.findUniqueOrThrow({ where: { id }, include: ticketInclude });
    });
  }

  async remove(id: string) {
    try { await this.prisma.ticket.delete({ where: { id } }); }
    catch (error) { if ((error as { code?: string }).code === 'P2003') throw new ConflictException('工单关联历史事项，不能删除追溯关系'); throw error; }
    return { success: true };
  }

  private async validateRelations(organizationId: string, dto: Partial<CreateTicketDto>) {
    const checks: Promise<unknown>[] = [];
    if (dto.assigneeId) {
      const assignee = await this.prisma.user.findFirst({ where: { id: dto.assigneeId, status: 'ACTIVE', role: { name: { in: ['admin', 'support', 'employee'] } } } });
      if (!assignee) throw new BadRequestException('负责人不存在、已停用或不是内部成员');
    }
    if (dto.contactId) checks.push(this.prisma.contact.findFirstOrThrow({ where: { id: dto.contactId, organizationId } }));
    if (dto.deviceId) checks.push(this.prisma.device.findFirstOrThrow({ where: { id: dto.deviceId, organizationId } }));
    if (dto.projectId) checks.push(this.prisma.project.findFirstOrThrow({ where: { id: dto.projectId, organizationId } }));
    try { await Promise.all(checks); } catch { throw new BadRequestException('联系人、设备或项目不属于所选客户'); }
  }

  /** RVC-YYMMDD-NNN：按本地日期当日顺序编号。并发冲突由 number 唯一约束 + 上层 P2002 重试兜底 */
  private async generateNumber(db: Prisma.TransactionClient) {
    const now = new Date();
    const ymd = `${String(now.getFullYear()).slice(2)}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`;
    const prefix = `RVC-${ymd}-`;
    const last = await db.ticket.findFirst({ where: { number: { startsWith: prefix } }, orderBy: { number: 'desc' }, select: { number: true } });
    const seq = last ? Number(last.number.slice(prefix.length)) + 1 : 1;
    return `${prefix}${String(seq).padStart(3, '0')}`;
  }

  async convertWorkItem(user: AuthUser, id: string, organizationId: string) {
    this.access.requireInternal(user);
    const original = await this.access.requireWorkItem(user, id);
    if (user.role === 'employee' && original.ownerId !== user.id) throw new ForbiddenException('只有负责人可以转换事项');
    await this.access.requireCustomer(user, organizationId);
    if (original.organizationId && original.organizationId !== organizationId) throw new BadRequestException('不能更改历史事项的客户归属');
    const converted = await this.prisma.$transaction(async (tx) => {
      await tx.$queryRaw`SELECT id FROM work_items WHERE id = ${id}::uuid FOR UPDATE`;
      const item = await tx.workItem.findUniqueOrThrow({ where: { id }, include: { workType: true, collaborators: true, worklogs: true } });
      if (item.convertedTicketId) return tx.ticket.findUniqueOrThrow({ where: { id: item.convertedTicketId }, include: ticketInclude });
      if (item.worklogs.some((log) => log.ticketId || (log.organizationId && log.organizationId !== organizationId))) throw new ConflictException('关联记录已有工单或客户冲突，请先整理后转换');
      const created = await this.create(user, { organizationId, projectId: item.projectId ?? undefined, title: item.title.length >= 3 ? item.title : `事项：${item.title}`, description: item.description || item.title.padEnd(3, ' '), category: ticketCategoryFromLabel(item.workType.label), assigneeId: item.ownerId, priority: item.priority, plannedAt: item.dueDate?.toISOString(), collaboratorIds: item.collaborators.map((c) => c.userId) }, tx);
      if (!created) throw new BadRequestException('转换失败');
      const status: TicketStatus = ({ TODO: 'PENDING', IN_PROGRESS: 'IN_PROGRESS', WAITING_FEEDBACK: 'WAITING_CUSTOMER', COMPLETED: 'RESOLVED', CANCELED: 'CLOSED' } as const)[item.status];
      await tx.ticket.update({ where: { id: created.id }, data: { status, resolvedAt: item.completedAt } });
      await tx.ticketEvent.create({ data: { ticketId: created.id, authorId: user.id, type: 'INTERNAL_NOTE', content: '由历史工作事项确认转换，原始数据保留', metadata: { workItemId: id, originalStatus: item.status, originalProgress: item.progress, originalCreatedAt: item.createdAt.toISOString(), tags: item.tags } } });
      await tx.workItem.update({ where: { id }, data: { convertedTicketId: created.id } });
      await tx.worklog.updateMany({ where: { workItemId: id, ticketId: null }, data: { ticketId: created.id, organizationId } });
      return tx.ticket.findUniqueOrThrow({ where: { id: created.id }, include: ticketInclude });
    });
    if (converted.assigneeId && converted.assigneeId !== user.id) await this.notifyAssignee(converted.id, converted.number, converted.assigneeId);
    return converted;
  }
}
