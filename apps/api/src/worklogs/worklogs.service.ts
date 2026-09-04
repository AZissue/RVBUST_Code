import { randomUUID } from 'node:crypto';
import { ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { WorklogSource, WorklogStatus } from '@prisma/client';
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

  list(user: AuthUser) {
    this.access.requireInternal(user);
    return this.prisma.worklog.findMany({ where: this.access.worklogWhere(user), include, orderBy: { occurredAt: 'desc' }, take: 500 });
  }

  async create(user: AuthUser, dto: CreateWorklogDto) {
    this.access.requireInternal(user);
    await this.validateRelations(dto.workTypeId, dto.organizationId, dto.ticketId, dto.workItemId, dto.projectId);
    return this.prisma.worklog.create({ data: { ...dto, occurredAt: new Date(dto.occurredAt), authorId: user.id, status: dto.status ?? WorklogStatus.CONFIRMED }, include });
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
    return this.prisma.worklog.update({ where: { id }, data: { ...dto, occurredAt: dto.occurredAt ? new Date(dto.occurredAt) : undefined }, include });
  }

  async remove(user: AuthUser, id: string) {
    this.access.requireInternal(user);
    const current = await this.prisma.worklog.findFirst({ where: { id, ...this.access.worklogWhere(user) } });
    if (!current) throw new NotFoundException('工作记录不存在');
    await this.prisma.worklog.delete({ where: { id } });
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
