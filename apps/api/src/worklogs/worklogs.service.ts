import { randomUUID } from 'node:crypto';
import { ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { TicketEventType, Visibility, WorkItemStatus, WorklogSource, WorklogStatus, type Prisma } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { CreateWorklogDraftsDto, CreateWorklogDto, UpdateWorklogDto } from './dto/worklog.dto.js';

const include = {
  organization: { select: { id: true, name: true } },
  ticket: { select: { id: true, number: true, title: true } },
  workItem: { select: { id: true, title: true } },
  project: { select: { id: true, name: true } },
  author: { select: { id: true, name: true } },
  workType: true,
} as const;

@Injectable()
export class WorklogsService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  list(user: AuthUser, ticketId?: string) {
    this.access.requireInternal(user);
    return this.prisma.worklog.findMany({ where: { AND: [this.access.worklogWhere(user), ...(ticketId ? [{ ticketId }] : [])] }, include, orderBy: { occurredAt: 'desc' }, take: 500 });
  }

  async create(user: AuthUser, dto: CreateWorklogDto) {
    this.access.requireInternal(user);
    await this.validateRelations(dto.workTypeId, dto.organizationId, dto.ticketId, dto.workItemId, dto.projectId);
    return this.prisma.$transaction(async (tx) => {
      const created = await tx.worklog.create({ data: { ...dto, occurredAt: new Date(dto.occurredAt), authorId: user.id, status: dto.status ?? WorklogStatus.CONFIRMED }, include });
      // ① 联动工单时间线：工作记录出现在事件流（单向，仅追加）
      if (dto.ticketId) await this.createWorkRecordEvent(tx, dto.ticketId, user.id, created);
      // ② 联动工作事项：TODO → IN_PROGRESS，进度兜底 ≥10（COMPLETED 不动，不改 completedAt，不自动完成）
      if (dto.workItemId) {
        const item = await tx.workItem.findUniqueOrThrow({ where: { id: dto.workItemId }, select: { status: true, progress: true } });
        if (item.status !== WorkItemStatus.COMPLETED && (item.status === WorkItemStatus.TODO || item.progress < 10)) {
          await tx.workItem.update({
            where: { id: dto.workItemId },
            data: { status: item.status === WorkItemStatus.TODO ? WorkItemStatus.IN_PROGRESS : undefined, progress: Math.max(item.progress, 10) },
          });
        }
      }
      return created;
    });
  }

  private createWorkRecordEvent(tx: Prisma.TransactionClient, ticketId: string, authorId: string, worklog: { id: string; summary: string; durationMinutes: number | null }) {
    return tx.ticketEvent.create({
      data: {
        ticketId, authorId,
        type: TicketEventType.WORK_RECORD,
        visibility: Visibility.INTERNAL,
        content: `工作记录：${worklog.summary}`,
        metadata: { worklogId: worklog.id, durationMinutes: worklog.durationMinutes ?? null },
      },
    });
  }

  /** 给联动事件打 timelineDeleted 软删标记（合并原 metadata，保留审计痕迹） */
  private async softDeleteLinkedEvents(tx: Prisma.TransactionClient, events: Array<{ id: string; metadata: unknown }>, deletedBy: string) {
    const deletedAt = new Date().toISOString();
    for (const event of events) {
      const metadata = event.metadata && typeof event.metadata === 'object' && !Array.isArray(event.metadata) ? event.metadata : {};
      await tx.ticketEvent.update({ where: { id: event.id }, data: { metadata: { ...metadata, timelineDeleted: true, timelineDeletedAt: deletedAt, timelineDeletedBy: deletedBy } } });
    }
  }

  async createDrafts(user: AuthUser, dto: CreateWorklogDraftsDto) {
    this.access.requireInternal(user);
    await this.validateRelations(dto.workTypeId);
    const aiExtractionId = randomUUID();
    const summaries = dto.summaries.map((value) => value.trim()).filter(Boolean);
    if (!summaries.length) throw new ForbiddenException('至少需要一条有效草稿');
    await this.prisma.worklog.createMany({ data: summaries.map((summary) => ({ authorId: user.id, workTypeId: dto.workTypeId, occurredAt: new Date(dto.occurredAt), summary: summary.slice(0, 240), rawText: dto.rawText, aiExtractionId, source: WorklogSource.AI_DRAFT, status: WorklogStatus.DRAFT })) });
    return this.prisma.worklog.findMany({ where: { aiExtractionId, authorId: user.id }, include, orderBy: { createdAt: 'asc' } });
  }

  async confirmDrafts(user: AuthUser, aiExtractionId: string) {
    this.access.requireInternal(user);
    const result = await this.prisma.worklog.updateMany({ where: { aiExtractionId, authorId: user.id, status: WorklogStatus.DRAFT }, data: { status: WorklogStatus.CONFIRMED } });
    if (!result.count) throw new NotFoundException('草稿批次不存在或已确认');
    return this.prisma.worklog.findMany({ where: { aiExtractionId, authorId: user.id }, include, orderBy: { createdAt: 'asc' } });
  }

  async update(user: AuthUser, id: string, dto: UpdateWorklogDto) {
    this.access.requireInternal(user);
    const current = await this.prisma.worklog.findFirst({ where: { id, ...this.access.worklogWhere(user) } });
    if (!current) throw new NotFoundException('工作记录不存在');
    if (current.authorId !== user.id && !['admin', 'support'].includes(user.role)) throw new ForbiddenException('无权修改此工作记录');
    await this.validateRelations(dto.workTypeId ?? current.workTypeId, dto.organizationId ?? current.organizationId ?? undefined, dto.ticketId ?? current.ticketId ?? undefined, dto.workItemId ?? current.workItemId ?? undefined, dto.projectId ?? current.projectId ?? undefined);
    return this.prisma.$transaction(async (tx) => {
      const updated = await tx.worklog.update({ where: { id }, data: { ...dto, occurredAt: dto.occurredAt ? new Date(dto.occurredAt) : undefined }, include });
      // 定位联动事件（metadata.worklogId 为锚点）
      const events = await tx.ticketEvent.findMany({ where: { type: TicketEventType.WORK_RECORD, metadata: { path: ['worklogId'], equals: id } } });
      const nextTicketId = dto.ticketId ?? current.ticketId ?? undefined;
      if (nextTicketId && nextTicketId !== current.ticketId) {
        // ticketId 变更（含裸记录首次关联）：旧工单事件软删，新工单补建事件
        await this.softDeleteLinkedEvents(tx, events, user.id);
        await this.createWorkRecordEvent(tx, nextTicketId, user.id, updated);
      } else if (nextTicketId) {
        // 摘要同步：联动事件 content 跟随更新；无联动事件（裸记录补挂等）则补建
        await tx.ticketEvent.updateMany({
          where: { type: TicketEventType.WORK_RECORD, metadata: { path: ['worklogId'], equals: id }, ticketId: nextTicketId },
          data: { content: `工作记录：${updated.summary}` },
        });
        if (!events.some((event) => event.ticketId === nextTicketId)) await this.createWorkRecordEvent(tx, nextTicketId, user.id, updated);
      }
      return updated;
    });
  }

  async remove(user: AuthUser, id: string) {
    this.access.requireInternal(user);
    const current = await this.prisma.worklog.findFirst({ where: { id, ...this.access.worklogWhere(user) } });
    if (!current) throw new NotFoundException('工作记录不存在');
    await this.prisma.$transaction(async (tx) => {
      // 软删联动事件（复用时间线删除模式），再删 worklog，单事务
      const events = await tx.ticketEvent.findMany({ where: { type: TicketEventType.WORK_RECORD, metadata: { path: ['worklogId'], equals: id } } });
      await this.softDeleteLinkedEvents(tx, events, user.id);
      await tx.worklog.delete({ where: { id } });
    });
    return { success: true };
  }

  private async validateRelations(workTypeId: string, organizationId?: string, ticketId?: string, workItemId?: string, projectId?: string) {
    if (!await this.prisma.workType.findFirst({ where: { id: workTypeId, isActive: true } })) throw new NotFoundException('工作分类不存在或已停用');
    let expectedOrganizationId = organizationId;
    let expectedProjectId = projectId;
    if (ticketId) {
      const ticket = await this.prisma.ticket.findUnique({ where: { id: ticketId }, select: { organizationId: true, projectId: true } });
      if (!ticket) throw new NotFoundException('工单不存在');
      if (expectedOrganizationId && ticket.organizationId !== expectedOrganizationId) throw new ForbiddenException('工单与所选客户不一致');
      if (expectedProjectId && ticket.projectId && ticket.projectId !== expectedProjectId) throw new ForbiddenException('工单与所选项目不一致');
      expectedOrganizationId ??= ticket.organizationId;
      expectedProjectId ??= ticket.projectId ?? undefined;
    }
    if (workItemId) {
      const item = await this.prisma.workItem.findUnique({ where: { id: workItemId }, select: { organizationId: true, projectId: true, convertedTicketId: true } });
      if (!item) throw new NotFoundException('工作事项不存在');
      if (item.convertedTicketId && ticketId !== item.convertedTicketId) throw new ForbiddenException('历史事项已转换，请关联对应工单');
      if (expectedOrganizationId && item.organizationId && item.organizationId !== expectedOrganizationId) throw new ForbiddenException('工作事项与所选客户不一致');
      if (expectedProjectId && item.projectId && item.projectId !== expectedProjectId) throw new ForbiddenException('工作事项与所选项目不一致');
    }
    if (projectId) {
      const project = await this.prisma.project.findUnique({ where: { id: projectId }, select: { organizationId: true } });
      if (!project) throw new NotFoundException('项目不存在');
      if (organizationId && project.organizationId && project.organizationId !== organizationId) throw new ForbiddenException('项目不属于所选客户');
    }
  }
}
