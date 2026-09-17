import { BadRequestException, ConflictException, ForbiddenException, Injectable, Logger, NotFoundException } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { TicketEventType, TicketStatus, Visibility, LoanStatus, RepairStatus, type Prisma } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { LinkageService } from '../linkage/linkage.service.js';
import { LINKAGE_EVENTS } from '../linkage/linkage.events.js';
import { NotificationsService } from '../notifications/notifications.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { ChangeStatusDto } from './dto/change-status.dto.js';
import { zhStatus } from '../common/status-labels.js';
import { CreateTicketEventDto } from './dto/ticket-event.dto.js';
import { CreateTicketDto, UpdateTicketDto, ChangeCreatorDto } from './dto/ticket.dto.js';
import { CreateAssistRequestDto } from './dto/assist.dto.js';
import { ticketCategoryFromLabel } from '../common/ticket-categories.js';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';
import { parseKey } from './quick-input.parser.js';
import { ticketViewWhere } from './ticket-filters.js';

const ticketInclude = {
  organization: { select: { id: true, name: true, level: true } },
  contact: true,
  device: true,
  project: true,
  assignee: { select: { id: true, name: true } },
  createdBy: { select: { id: true, name: true } },
  deletedBy: { select: { id: true, name: true } },
  collaborators: { include: { user: { select: { id: true, name: true } } } },
  assistRequests: { include: { requester: { select: { id: true, name: true } }, targetUser: { select: { id: true, name: true } } }, orderBy: { createdAt: 'desc' } },
} as const;

const transitions: Record<TicketStatus, TicketStatus[]> = {
  PENDING: [TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  IN_PROGRESS: [TicketStatus.PENDING, TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  WAITING_CUSTOMER: [TicketStatus.PENDING, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_RND, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  WAITING_RND: [TicketStatus.PENDING, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.RESOLVED, TicketStatus.CLOSED],
  RESOLVED: [TicketStatus.PENDING, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.CLOSED],
  CLOSED: [TicketStatus.PENDING, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_CUSTOMER, TicketStatus.WAITING_RND, TicketStatus.RESOLVED],
};

const PAGE_SIZE = 20;
const visibleInclude = (_user: AuthUser) => ({ ...ticketInclude });

// 进行中的子单状态集合（与 linkage 模块一致）：存在时不允许将工单标记为已解决
const ACTIVE_LOAN_STATUSES: LoanStatus[] = [LoanStatus.QUEUED, LoanStatus.ONGOING, LoanStatus.OVERDUE];
const ACTIVE_REPAIR_STATUSES: RepairStatus[] = [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING, RepairStatus.SHIPPED];

@Injectable()
export class TicketsService {
  private readonly logger = new Logger(TicketsService.name);
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService, private readonly notifications: NotificationsService, private readonly linkage: LinkageService, private readonly events: EventEmitter2) {}

  private notifyAssignee(ticketId: string, number: string, assigneeId: string) {    return this.notifications.notify({
      recipientId: assigneeId, ticketId, type: NOTIFICATION_TYPES.TICKET_ASSIGNED, title: '工单已指派给你',
      body: `工单 ${number} 已指派给你处理。`, dedupeKey: `ticket-assign:${ticketId}:${assigneeId}`,
    });
  }

  private buildWhere(user: AuthUser, search: string | undefined, statuses: TicketStatus[] | undefined, mine: boolean, view?: string): Prisma.TicketWhereInput {
    return {
      // 回收站：普通列表只显示未删除工单
      deletedAt: null,
      AND: [this.access.ticketWhere(user), ticketViewWhere(user.id, view), ...(mine && !view ? [{ assigneeId: user.id }] : [])],
      ...(statuses?.length ? { status: { in: statuses } } : {}),
      ...(search ? { OR: [{ number: { contains: search, mode: 'insensitive' } }, { title: { contains: search, mode: 'insensitive' } }, { description: { contains: search, mode: 'insensitive' } }, { cameraModel: { contains: search, mode: 'insensitive' } }, { device: { name: { contains: search, mode: 'insensitive' } } }, { organization: { name: { contains: search, mode: 'insensitive' } } }] } : {}),
    };
  }

  /** 分页列表：20 条/页，附带总数与状态分布（工作台指标用） */
  async list(user: AuthUser, search: string | undefined, statuses: TicketStatus[] | undefined, mine: boolean, page: number, view?: string) {
    const where = this.buildWhere(user, search, statuses, mine, view);
    const metricsWhere = this.buildWhere(user, search, undefined, mine, view);
    const safePage = Math.max(1, Math.min(page, 10000));
    const statusList = Object.values(TicketStatus);
    const [total, items, ...statusCounts] = await this.prisma.$transaction([
      this.prisma.ticket.count({ where }),
      this.prisma.ticket.findMany({ where, include: visibleInclude(user), omit: { rawText: false, requestKey: true, deletedReason: false }, orderBy: [{ number: 'desc' }], skip: (safePage - 1) * PAGE_SIZE, take: PAGE_SIZE }),
      ...statusList.map((status) => this.prisma.ticket.count({ where: { AND: [metricsWhere, { status }] } })),
    ]);
    return { items, total, page: safePage, pageSize: PAGE_SIZE, byStatus: Object.fromEntries(statusList.map((status, index) => [status, statusCounts[index]])) as Partial<Record<TicketStatus, number>> };
  }

  /** 全量列表（引用数据下拉用，如工作记录关联工单）；数据量大时请改用分页 list */
  listAll(user: AuthUser, search?: string, statuses?: TicketStatus[], mine = false) {
    return this.prisma.ticket.findMany({ where: this.buildWhere(user, search, statuses, mine), include: visibleInclude(user), omit: { rawText: false, requestKey: true, deletedReason: false }, orderBy: [{ number: 'desc' }] });
  }

  async get(user: AuthUser, id: string) {
    const ticket = await this.access.requireTicket(user, id);
    const result = await this.prisma.ticket.findUnique({
      where: { id },
      omit: { rawText: false, requestKey: true },
      include: {
        ...visibleInclude(user),
        events: {
          include: { author: { select: { id: true, name: true, role: { select: { name: true } } } }, attachments: true },
          orderBy: { createdAt: 'asc' },
        },
        attachments: true,
        loanOrders: { select: { id: true, loanNo: true, status: true, infoComplete: true }, orderBy: { createdAt: 'desc' as const } },
        repairOrders: { select: { id: true, repairNo: true, status: true }, orderBy: { createdAt: 'desc' as const } },
      },
    });
    if (!result) return result;
    return { ...result, events: result.events.filter(event => !(event.metadata && typeof event.metadata === 'object' && !Array.isArray(event.metadata) && event.metadata.timelineDeleted === true)) };
  }

  async removeEvent(user: AuthUser, ticketId: string, eventId: string, reason: string) {
    if (!reason.trim()) throw new BadRequestException('请填写删除原因');
    await this.access.requireTicket(user, ticketId);
    return this.prisma.$transaction(async tx => {
      // 保留原记录及附件，只隐藏时间线；审计与隐藏必须同时成功。
      await tx.$queryRaw`SELECT id FROM ticket_events WHERE id = ${eventId}::uuid AND ticket_id = ${ticketId}::uuid FOR UPDATE`;
      const event = await tx.ticketEvent.findFirst({ where: { id: eventId, ticketId } });
      if (!event) throw new NotFoundException('流程记录不存在');
      const metadata = event.metadata && typeof event.metadata === 'object' && !Array.isArray(event.metadata) ? event.metadata : {};
      if (metadata.timelineDeleted === true) throw new ConflictException('该记录已被删除，请刷新');
      if (user.role !== 'admin' && event.authorId !== user.id) throw new ForbiddenException('仅管理员或记录作者可以删除流程记录');
      const deletedAt = new Date().toISOString();
      await tx.auditLog.create({ data: { actorId: user.id, action: 'ticket.event.delete', entityType: 'TicketEvent', entityId: eventId, metadata: { ticketId, reason: reason.trim(), deletedAt, original: { authorId: event.authorId, type: event.type, visibility: event.visibility, content: event.content, metadata: event.metadata, createdAt: event.createdAt.toISOString() } } } });
      await tx.ticketEvent.update({ where: { id: eventId }, data: { metadata: { ...metadata, timelineDeleted: true, timelineDeletedAt: deletedAt, timelineDeletedBy: user.id } } });
      return { success: true };
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
    const organizationId = dto.organizationId;
    if (!organizationId) throw new BadRequestException('请选择客户公司');
    await this.access.requireCustomer(user, organizationId);
    await this.validateRelations(organizationId, dto);
    // 协助对象直接作为协作人写入（无接受/驳回环节），与手动指定的协作人合并去重
    const assistTargetIds = [...new Set(dto.assistTargetIds ?? [])];
    if (assistTargetIds.length) await this.resolveAssistTargets(this.prisma, user.id, assistTargetIds);
    const collaboratorIds = [...new Set([...(dto.collaboratorIds ?? []), ...assistTargetIds])];
    const assigneeId = dto.assigneeId ?? user.id;
    // 补录历史工单：occurredAt（本地日期）决定 createdAt 与编号日期
    const occurredAt = dto.occurredAt ? parseKey(dto.occurredAt) : undefined;
    // 内部用户可指定创建时状态（补录场景）
    const initialStatus = dto.status;
    const data: Omit<Prisma.TicketCreateInput, 'number'> = {
      createdAt: occurredAt,
      status: initialStatus,
      resolvedAt: initialStatus === TicketStatus.RESOLVED ? (occurredAt ?? new Date()) : undefined,
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
      events: { create: { author: { connect: { id: user.id } }, type: TicketEventType.WORK_RECORD, visibility: Visibility.INTERNAL, content: initialStatus ? `工单已创建（${zhStatus(initialStatus)}）` : '工单已创建' } },
    };
    const createRecord = async (client: Prisma.TransactionClient) => {
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
          return await client.ticket.create({ data: { ...data, number: await this.generateNumber(client, occurredAt) }, include: ticketInclude });
        }
        catch (error) {
          if ((error as { code?: string }).code !== 'P2002' || attempt === 3) throw error;
          if (dto.requestKey) {
            const existing = await client.ticket.findUnique({ where: { requestKey: dto.requestKey }, include: ticketInclude });
            if (existing?.createdById === user.id) return existing;
            if (existing) throw new ConflictException('提交标识已使用');
          }
        }
      }
      throw new ConflictException('工单编号生成失败，请重试');
    };
    const created = await createRecord(db);
    // 接续同客户未解决工单：关联留痕 + 按 autoClose 关闭前置单（同事务，失败整体回滚）
    if (dto.continuations?.length) await this.applyContinuations(user, created, dto, db);
    // 事务内调用（如事项转换）跳过通知，由外层在事务提交后补发，避免引用未提交工单
    if (db === this.prisma && assigneeId && assigneeId !== user.id) await this.notifyAssignee(created.id, created.number, assigneeId);
    // 联动创建借测/维修单：单个联动失败仅记录日志并反馈给前端，不影响工单本身与另一路联动
    const linkageErrors: string[] = [];
    if (db === this.prisma && dto.createLinkedLoan) {
      try { await this.linkage.createLoanFromTicket(user, created.id); }
      catch (error) {
        this.logger.error(`工单 ${created.number} 联动创建借测单失败`, error as Error);
        linkageErrors.push(`借测单创建失败：${(error as { message?: string }).message ?? '未知错误'}`);
      }
    }
    if (db === this.prisma && dto.createLinkedRepair) {
      try { await this.linkage.createRepairFromTicket(user, created.id); }
      catch (error) {
        this.logger.error(`工单 ${created.number} 联动创建维修单失败`, error as Error);
        linkageErrors.push(`维修单创建失败：${(error as { message?: string }).message ?? '未知错误'}`);
      }
    }
    // 联动失败信息随响应返回，前端据此提示用户补建
    return linkageErrors.length ? Object.assign(created, { linkageErrors }) : created;
  }

  /**
   * 接续同客户未解决工单（在 create 事务内调用，失败整体回滚）：
   * 校验（同客户/未解决/未被接续过）→ 写关联 → 双向时间线 → 按 autoClose 关闭前置单
   * （carryLinks 时迁移进行中借测/维修单到新单，兼容 M3 关单拦截）→ 通知原负责人与创建人。
   */
  private async applyContinuations(user: AuthUser, created: { id: string; number: string; organizationId: string }, dto: CreateTicketDto, db: Prisma.TransactionClient) {
    const items = dto.continuations!;
    const unique = new Map(items.map((item) => [item.fromTicketId, item.note.trim()]));
    if (unique.size !== items.length) throw new BadRequestException('接续工单存在重复项');
    const autoClose = dto.autoClose ?? true;
    const carryLinks = dto.carryLinks ?? false;
    const fromIds = [...unique.keys()];
    for (const note of unique.values()) {
      if (note.length < 2 || note.length > 500) throw new BadRequestException('接续说明需为 2-500 字');
    }
    const predecessors = await db.ticket.findMany({
      where: { id: { in: fromIds } },
      select: { id: true, number: true, title: true, status: true, organizationId: true, deletedAt: true, assigneeId: true, createdById: true },
    });
    for (const id of fromIds) {
      const p = predecessors.find((item) => item.id === id);
      if (!p || p.deletedAt) throw new BadRequestException('前置工单不存在或已删除');
      if (p.organizationId !== created.organizationId) throw new BadRequestException(`工单 ${p.number} 与该客户不一致，不能接续`);
      if (p.status === TicketStatus.RESOLVED || p.status === TicketStatus.CLOSED) throw new BadRequestException(`工单 ${p.number} 已${p.status === TicketStatus.CLOSED ? '关闭' : '解决'}，不能接续`);
    }
    // 线性链：一张前置单最多被接续一次（fromTicketId 唯一索引兜底并发）
    const existed = await db.ticketContinuation.findFirst({ where: { fromTicketId: { in: fromIds } }, select: { fromTicketId: true, toTicket: { select: { number: true } } }, orderBy: { createdAt: 'asc' } });
    if (existed) throw new BadRequestException(`工单已被 ${existed.toTicket.number} 接续，请勿重复接续`);
    // 自动关单前检查进行中借测/维修单（M3 关单拦截条件）
    if (autoClose && !carryLinks) {
      const [loans, repairs] = await Promise.all([
        db.loanOrder.findMany({ where: { ticketId: { in: fromIds }, deletedAt: null, status: { in: ACTIVE_LOAN_STATUSES } }, select: { loanNo: true } }),
        db.repairOrder.findMany({ where: { ticketId: { in: fromIds }, deletedAt: null, status: { in: ACTIVE_REPAIR_STATUSES } }, select: { repairNo: true } }),
      ]);
      if (loans.length || repairs.length) throw new BadRequestException(`前置工单存在进行中的借测/维修单（${[...loans.map((l) => l.loanNo), ...repairs.map((r) => r.repairNo)].join('、')}），请先处理或勾选「迁移关联业务到新单」`);
    }
    const truncate = (text: string, max: number) => (text.length > max ? text.slice(0, max) : text);
    for (const [fromId, note] of unique) {
      const p = predecessors.find((item) => item.id === fromId)!;
      const link = await db.ticketContinuation.create({ data: { fromTicketId: fromId, toTicketId: created.id, note, carryLinks, createdById: user.id } });
      const meta = { continuationId: link.id, fromNumber: p.number, toNumber: created.number };
      // 前置单时间线：接续留痕（自动关单/仅关联两种文案）
      await db.ticketEvent.create({ data: { ticketId: fromId, authorId: user.id, type: TicketEventType.LINK_CREATED, visibility: Visibility.INTERNAL, content: autoClose ? `本工单由 ${created.number} 接续跟进：${note}，工单关闭` : `本工单被 ${created.number} 关联引用：${note}`, metadata: meta } });
      // 新单时间线：承接自前置单
      await db.ticketEvent.create({ data: { ticketId: created.id, authorId: user.id, type: TicketEventType.LINK_CREATED, visibility: Visibility.INTERNAL, content: `接续自 ${p.number}「${truncate(p.title, 40)}」：${note}`, metadata: meta } });
      if (!autoClose) continue;
      // 迁移进行中的借测/维修单到新单（两边时间线各留一条）
      if (carryLinks) {
        const [loans, repairs] = await Promise.all([
          db.loanOrder.findMany({ where: { ticketId: fromId, deletedAt: null, status: { in: ACTIVE_LOAN_STATUSES } }, select: { id: true, loanNo: true } }),
          db.repairOrder.findMany({ where: { ticketId: fromId, deletedAt: null, status: { in: ACTIVE_REPAIR_STATUSES } }, select: { id: true, repairNo: true } }),
        ]);
        for (const loan of loans) {
          await db.loanOrder.update({ where: { id: loan.id }, data: { ticketId: created.id } });
          await db.ticketEvent.create({ data: { ticketId: fromId, authorId: user.id, type: TicketEventType.LINK_UPDATE, visibility: Visibility.INTERNAL, content: `借测单 ${loan.loanNo} 的关联工单已变更为 ${created.number}（接续迁移）`, metadata: { linkType: 'loan', linkId: loan.id, linkNo: loan.loanNo, migratedTo: created.number } } });
          await db.ticketEvent.create({ data: { ticketId: created.id, authorId: user.id, type: TicketEventType.LINK_UPDATE, visibility: Visibility.INTERNAL, content: `承接迁移自 ${p.number} 的借测单 ${loan.loanNo}`, metadata: { linkType: 'loan', linkId: loan.id, linkNo: loan.loanNo, migratedFrom: p.number } } });
        }
        for (const repair of repairs) {
          await db.repairOrder.update({ where: { id: repair.id }, data: { ticketId: created.id } });
          await db.ticketEvent.create({ data: { ticketId: fromId, authorId: user.id, type: TicketEventType.LINK_UPDATE, visibility: Visibility.INTERNAL, content: `维修单 ${repair.repairNo} 的关联工单已变更为 ${created.number}（接续迁移）`, metadata: { linkType: 'repair', linkId: repair.id, linkNo: repair.repairNo, migratedTo: created.number } } });
          await db.ticketEvent.create({ data: { ticketId: created.id, authorId: user.id, type: TicketEventType.LINK_UPDATE, visibility: Visibility.INTERNAL, content: `承接迁移自 ${p.number} 的维修单 ${repair.repairNo}`, metadata: { linkType: 'repair', linkId: repair.id, linkNo: repair.repairNo, migratedFrom: p.number } } });
        }
      }
      // 关闭前置单（接续关闭：solution 记入接续说明，不设 resolvedAt，报表口径不受影响）
      await db.ticket.update({ where: { id: fromId }, data: { status: TicketStatus.CLOSED, solution: note } });
      await db.ticketEvent.create({ data: { ticketId: fromId, authorId: user.id, type: TicketEventType.STATUS_CHANGE, visibility: Visibility.INTERNAL, content: `状态变更：${zhStatus(p.status)} → 已关闭（由接续工单关闭）` } });
    }
    // 通知前置单负责人与创建人（事务内调用时由外层补发，避免引用未提交工单）
    if (db === this.prisma) {
      for (const [fromId] of unique) {
        const p = predecessors.find((item) => item.id === fromId)!;
        const recipients = [...new Set([p.assigneeId, p.createdById])].filter((rid): rid is string => Boolean(rid) && rid !== user.id);
        for (const recipientId of recipients) {
          await this.notifications.notify({
            recipientId, ticketId: fromId, type: NOTIFICATION_TYPES.TICKET_CONTINUED,
            title: autoClose ? '工单已被接续并关闭' : '工单被新单关联引用',
            body: autoClose ? `${user.name} 将工单 ${p.number} 接续到新工单 ${created.number}，原工单已关闭。` : `${user.name} 将工单 ${p.number} 关联引用到新工单 ${created.number}。`,
            dedupeKey: `ticket-continued:${fromId}:${created.id}:${recipientId}`,
          });
        }
      }
    }
  }

  /** 接续选择器数据源：该客户近 90 天未解决、未被接续的工单（附进行中借测/维修数，供迁移提示） */
  async continuable(user: AuthUser, organizationId: string, keyword?: string) {
    await this.access.requireCustomer(user, organizationId);
    const since = new Date(Date.now() - 90 * 86400000);
    const search = (keyword ?? '').trim();
    return this.prisma.ticket.findMany({
      where: {
        AND: [this.access.ticketWhere(user)],
        organizationId, deletedAt: null,
        status: { notIn: [TicketStatus.RESOLVED, TicketStatus.CLOSED] },
        createdAt: { gte: since },
        continuationsFrom: { none: {} },
        ...(search ? { OR: [{ number: { contains: search, mode: 'insensitive' } }, { title: { contains: search, mode: 'insensitive' } }] } : {}),
      },
      select: {
        id: true, number: true, title: true, status: true, updatedAt: true,
        assignee: { select: { id: true, name: true } },
        loanOrders: { where: { deletedAt: null, status: { in: ACTIVE_LOAN_STATUSES } }, select: { id: true } },
        repairOrders: { where: { deletedAt: null, status: { in: ACTIVE_REPAIR_STATUSES } }, select: { id: true } },
      },
      orderBy: { updatedAt: 'desc' },
      take: 20,
    });
  }

  /** 工单链：向上（承接自）/向下（已接续至）各遍历 ≤10 跳，环安全；已删除单标注 */
  async chain(user: AuthUser, id: string) {
    await this.access.requireTicket(user, id);
    const walk = async (startId: string, direction: 'from' | 'to') => {
      const result: { id: string; number: string; title: string; status: TicketStatus; deletedAt: string | null; note: string; createdAt: string }[] = [];
      const visited = new Set<string>([startId]);
      let frontier = [startId];
      for (let hop = 0; hop < 10 && frontier.length; hop++) {
        const links = await this.prisma.ticketContinuation.findMany({
          where: direction === 'from' ? { toTicketId: { in: frontier } } : { fromTicketId: { in: frontier } },
          select: { note: true, createdAt: true, fromTicket: { select: { id: true, number: true, title: true, status: true, deletedAt: true } }, toTicket: { select: { id: true, number: true, title: true, status: true, deletedAt: true } } },
        });
        const next: string[] = [];
        for (const link of links) {
          const ticket = direction === 'from' ? link.fromTicket : link.toTicket;
          if (visited.has(ticket.id)) continue;
          visited.add(ticket.id);
          next.push(ticket.id);
          result.push({ id: ticket.id, number: ticket.number, title: ticket.title, status: ticket.status, deletedAt: ticket.deletedAt ? ticket.deletedAt.toISOString() : null, note: link.note, createdAt: link.createdAt.toISOString() });
        }
        frontier = next;
      }
      return result.reverse();
    };
    const [ancestors, descendants] = await Promise.all([walk(id, 'from'), walk(id, 'to')]);
    return { ancestors, descendants };
  }

  /** 校验并返回可协助的内部成员（去重、排除本人、需为启用账号）；否则抛错 */
  private async resolveAssistTargets(db: Prisma.TransactionClient, requesterId: string, targetIds: string[]) {
    if (!targetIds.length) return [];
    const unique = [...new Set(targetIds)];
    if (unique.includes(requesterId)) throw new BadRequestException('不能添加自己为协作人');
    const targets = await db.user.findMany({ where: { id: { in: unique }, status: 'ACTIVE', role: { name: { in: ['admin', 'support', 'employee'] } } }, select: { id: true, name: true } });
    const found = new Map(targets.map((item) => [item.id, item.name]));
    const invalid = unique.filter((id) => !found.has(id));
    if (invalid.length) throw new BadRequestException('协作人不存在、已停用或不是内部成员');
    return unique.map((id) => ({ id, name: found.get(id)! }));
  }

  async update(user: AuthUser, id: string, dto: UpdateTicketDto) {
    const current = await this.access.requireTicket(user, id);
    this.assertActive(current);
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
    const ticket = await this.access.requireTicket(user, id);
    this.assertActive(ticket);
    if (user.role !== 'admin' && ticket.assigneeId !== user.id) throw new ForbiddenException('仅当前负责人或管理员可以变更工单状态');
    if (!transitions[ticket.status].includes(dto.status)) throw new BadRequestException(`不允许从「${zhStatus(ticket.status)}」变更为「${zhStatus(dto.status)}」`);
    return this.prisma.$transaction(async (tx) => {
      // 关单拦截（状态汇聚）：目标为已解决时，存在进行中的借测/维修单则拒绝
      if (dto.status === TicketStatus.RESOLVED) {
        const [activeLoans, activeRepairs] = await Promise.all([
          tx.loanOrder.findMany({ where: { ticketId: id, status: { in: ACTIVE_LOAN_STATUSES }, deletedAt: null }, select: { loanNo: true } }),
          tx.repairOrder.findMany({ where: { ticketId: id, status: { in: ACTIVE_REPAIR_STATUSES }, deletedAt: null }, select: { repairNo: true } }),
        ]);
        const parts = [
          activeLoans.length ? `借测单 ${activeLoans.map((loan) => loan.loanNo).join('、')}` : '',
          activeRepairs.length ? `维修单 ${activeRepairs.map((repair) => repair.repairNo).join('、')}` : '',
        ].filter(Boolean);
        if (parts.length) throw new BadRequestException(`存在进行中的${parts.join(' / ')}，完结关联业务后才能标记解决`);
      }
      const changed = await tx.ticket.updateMany({
        where: { id, status: ticket.status, updatedAt: ticket.updatedAt },
        data: { status: dto.status, resolvedAt: dto.status === TicketStatus.RESOLVED ? new Date() : dto.status === TicketStatus.CLOSED ? undefined : null },
      });
      if (changed.count !== 1) throw new ConflictException('工单已被其他人修改，请刷新后重试');
      const updated = await tx.ticket.findUniqueOrThrow({ where: { id }, include: ticketInclude });
      const event = await tx.ticketEvent.create({
        data: { ticketId: id, authorId: user.id, type: TicketEventType.STATUS_CHANGE, visibility: Visibility.INTERNAL, content: `${ticket.status} -> ${dto.status}${dto.reason ? `：${dto.reason}` : ''}`, metadata: { from: ticket.status, to: dto.status } },
      });
      const recipients = [...new Set([updated.createdBy.id, updated.assignee?.id, ...updated.collaborators.map((item) => item.user.id)])].filter((id): id is string => Boolean(id) && id !== user.id);
      await tx.notification.createMany({ data: recipients.map((recipientId) => ({
        recipientId, ticketId: id, type: NOTIFICATION_TYPES.TICKET_STATUS_CHANGED,
        title: '工单状态已更新',
        body: `${user.name} 将工单 ${updated.number}「${updated.title}」从「${zhStatus(ticket.status)}」改为「${zhStatus(dto.status)}」`,
        dedupeKey: `ticket-status:${event.id}:${recipientId}`,
      })) });
      return updated;
    });
  }

  async addEvent(user: AuthUser, id: string, dto: CreateTicketEventDto) {
    const ticket = await this.access.requireTicket(user, id);
    this.assertActive(ticket);
    // 内部备注（排查过程）允许所有内部成员在任何工单下追加，便于协作排查；
    // 客户可见回复及其他类型的写入仍仅限创建人、负责人或管理员。
    const isInternalNote = dto.type === TicketEventType.INTERNAL_NOTE;
    if (!isInternalNote && !this.access.canEditTicket(user, ticket)) throw new ForbiddenException('仅创建人、负责人或管理员可以更新该工单');
    const type = dto.type;
    const visibility = type === TicketEventType.INTERNAL_NOTE ? Visibility.INTERNAL : (dto.visibility ?? Visibility.INTERNAL);
    const event = await this.prisma.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type, visibility, content: dto.content }, include: { author: { select: { id: true, name: true } } } });
    // 客户回复正向同步到进行中的借测/维修单跟进（由 linkage 监听器落地，不回写工单，避免回声）
    if (type === TicketEventType.CUSTOMER_REPLY) {
      this.events.emit(LINKAGE_EVENTS.ticketCustomerReply, { ticketId: id, actorId: user.id, content: dto.content });
    }
    return event;
  }

  async changeCreator(user: AuthUser, id: string, dto: ChangeCreatorDto) {
    const current = await this.access.requireTicket(user, id);
    this.assertActive(current);
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

  /** 移入回收站（软删除）：保留数据与操作记录 */
  async softDelete(user: AuthUser, id: string, reason?: string) {
    const ticket = await this.access.requireTicket(user, id);
    if (!this.access.canEditTicket(user, ticket)) throw new ForbiddenException('仅创建人、负责人或管理员可以删除该工单');
    if (ticket.deletedAt) throw new BadRequestException('工单已在回收站中');
    return this.prisma.$transaction(async (tx) => {
      const updated = await tx.ticket.update({ where: { id }, data: { deletedAt: new Date(), deletedById: user.id, deletedReason: reason || null }, include: ticketInclude });
      const event = await tx.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type: TicketEventType.DELETE, visibility: Visibility.INTERNAL, content: `工单被移入回收站${reason ? `，原因：${reason}` : ''}` } });
      const recipients = [...new Set([updated.createdBy.id, updated.assignee?.id])].filter((recipientId): recipientId is string => Boolean(recipientId) && recipientId !== user.id);
      if (recipients.length) await tx.notification.createMany({ data: recipients.map((recipientId) => ({ recipientId, ticketId: id, type: NOTIFICATION_TYPES.TICKET_DELETED, title: '工单被移入回收站', body: `${user.name} 将工单 ${updated.number}「${updated.title}」移入回收站${reason ? `，原因：${reason}` : ''}`, dedupeKey: `ticket-deleted:${event.id}:${recipientId}` })) });
      return updated;
    });
  }

  /** 回收站列表（仅显示已删除工单） */
  async listDeleted(user: AuthUser, search: string | undefined, page: number) {
    const where: Prisma.TicketWhereInput = {
      deletedAt: { not: null },
      ...(search ? { OR: [{ number: { contains: search, mode: 'insensitive' } }, { title: { contains: search, mode: 'insensitive' } }, { description: { contains: search, mode: 'insensitive' } }, { organization: { name: { contains: search, mode: 'insensitive' } } }] } : {}),
    };
    const safePage = Math.max(1, Math.min(page, 10000));
    const [total, items] = await this.prisma.$transaction([
      this.prisma.ticket.count({ where }),
      this.prisma.ticket.findMany({ where, include: ticketInclude, omit: { rawText: true, requestKey: true }, orderBy: { deletedAt: 'desc' }, skip: (safePage - 1) * PAGE_SIZE, take: PAGE_SIZE }),
    ]);
    return { items, total, page: safePage, pageSize: PAGE_SIZE };
  }

  /** 从回收站恢复工单 */
  async restore(user: AuthUser, id: string) {
    const ticket = await this.access.requireTicket(user, id);
    if (!ticket.deletedAt) throw new BadRequestException('工单不在回收站中');
    if (user.role !== 'admin' && user.role !== 'support' && user.id !== ticket.deletedById && !this.access.canEditTicket(user, ticket)) throw new ForbiddenException('仅管理员、支持人员或相关负责人可以恢复该工单');
    return this.prisma.$transaction(async (tx) => {
      const updated = await tx.ticket.update({ where: { id }, data: { deletedAt: null, deletedById: null, deletedReason: null }, include: ticketInclude });
      await tx.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type: TicketEventType.RESTORE, visibility: Visibility.INTERNAL, content: '工单已从回收站恢复' } });
      return updated;
    });
  }

  /** 彻底删除回收站中的工单（仅管理员） */
  async purge(user: AuthUser, id: string) {
    if (user.role !== 'admin') throw new ForbiddenException('仅管理员可以彻底删除工单');
    const ticket = await this.prisma.ticket.findUnique({ where: { id }, select: { deletedAt: true } });
    if (!ticket) throw new NotFoundException('工单不存在');
    if (!ticket.deletedAt) throw new BadRequestException('仅回收站中的工单可以彻底删除');
    try { await this.prisma.ticket.delete({ where: { id } }); }
    catch (error) { if ((error as { code?: string }).code === 'P2003') throw new ConflictException('工单关联历史事项，不能彻底删除追溯关系'); throw error; }
    return { success: true };
  }

  /** 直接添加协作人：无接受/驳回环节，添加后即可查看工单并参与跟进 */
  async createAssistRequests(user: AuthUser, id: string, dto: CreateAssistRequestDto) {
    const ticket = await this.access.requireTicket(user, id);
    this.assertActive(ticket);
    if (!this.access.canEditTicket(user, ticket)) throw new ForbiddenException('仅创建人、负责人或管理员可以添加协作人');
    const targets = await this.resolveAssistTargets(this.prisma, user.id, dto.targetUserIds);
    if (!targets.length) throw new BadRequestException('请选择协作人');
    await this.prisma.$transaction(async (tx) => {
      await tx.$queryRaw`SELECT id FROM tickets WHERE id = ${ticket.id}::uuid FOR UPDATE`;
      this.assertActive(await tx.ticket.findUniqueOrThrow({ where: { id: ticket.id } }));
      const existing = await tx.ticketCollaborator.findMany({ where: { ticketId: ticket.id, userId: { in: targets.map((target) => target.id) } }, select: { userId: true } });
      const existed = new Set(existing.map((item) => item.userId));
      const fresh = targets.filter((target) => !existed.has(target.id));
      if (!fresh.length) throw new ConflictException('所选人员已是协作人');
      for (const target of fresh) {
        await tx.ticketCollaborator.create({ data: { ticketId: ticket.id, userId: target.id } });
        await tx.ticketEvent.create({ data: { ticketId: ticket.id, authorId: user.id, type: TicketEventType.ASSIST_REQUEST, visibility: Visibility.INTERNAL, content: `邀请 ${target.name} 协助${dto.message ? `：${dto.message}` : ''}` } });
      }
      await tx.notification.createMany({ data: fresh.map((target) => ({ recipientId: target.id, ticketId: ticket.id, type: NOTIFICATION_TYPES.TICKET_ASSIST_REQUESTED, title: '邀请你协助工单', body: `${user.name} 邀请你协助工单 ${ticket.number}「${ticket.title}」${dto.message ? `：${dto.message}` : ''}` })) });
    });
    return this.prisma.ticket.findUniqueOrThrow({ where: { id }, include: ticketInclude });
  }

  /** 移除协作人（仅创建人、负责人或管理员） */
  async removeCollaborator(user: AuthUser, id: string, collaboratorUserId: string) {
    const ticket = await this.access.requireTicket(user, id);
    this.assertActive(ticket);
    if (!this.access.canEditTicket(user, ticket)) throw new ForbiddenException('仅创建人、负责人或管理员可以移除协作人');
    await this.prisma.$transaction(async (tx) => {
      const removed = await tx.ticketCollaborator.deleteMany({ where: { ticketId: id, userId: collaboratorUserId } });
      if (!removed.count) throw new NotFoundException('该用户不是协作人');
      const target = await tx.user.findUniqueOrThrow({ where: { id: collaboratorUserId }, select: { name: true } });
      await tx.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type: TicketEventType.INTERNAL_NOTE, visibility: Visibility.INTERNAL, content: `${user.name} 移除了协作人 ${target.name}` } });
    });
    return this.prisma.ticket.findUniqueOrThrow({ where: { id }, include: ticketInclude });
  }

  private assertActive(ticket: { deletedAt?: Date | null }) {
    if (ticket.deletedAt) throw new BadRequestException('工单已在回收站中，请先恢复');
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

  /** RVC-YYMMDD-NNN：按本地日期当日顺序编号（可指定补录日期）。并发冲突由 number 唯一约束 + 上层 P2002 重试兜底 */
  private async generateNumber(db: Prisma.TransactionClient, date = new Date()) {
    const ymd = `${String(date.getFullYear()).slice(2)}${String(date.getMonth() + 1).padStart(2, '0')}${String(date.getDate()).padStart(2, '0')}`;
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
