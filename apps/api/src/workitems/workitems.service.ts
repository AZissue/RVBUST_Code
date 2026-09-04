import { ConflictException, ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { WorkItemStatus } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { CreateWorkItemDto, UpdateWorkItemDto } from './dto/work-item.dto.js';

const include = {
  workType: true,
  organization: { select: { id: true, name: true } },
  project: { select: { id: true, name: true } },
  owner: { select: { id: true, name: true } },
  collaborators: { include: { user: { select: { id: true, name: true } } } },
  _count: { select: { worklogs: true } },
} as const;

@Injectable()
export class WorkitemsService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  list(user: AuthUser, mine = false) {
    this.access.requireInternal(user);
    const scope = this.access.workItemWhere(user);
    const where = mine ? { AND: [scope, { OR: [{ ownerId: user.id }, { collaborators: { some: { userId: user.id } } }] }] } : scope;
    return this.prisma.workItem.findMany({ where, include, orderBy: [{ status: 'asc' }, { dueDate: 'asc' }, { updatedAt: 'desc' }], take: 500 });
  }

  async get(user: AuthUser, id: string) {
    await this.access.requireWorkItem(user, id);
    const item = await this.prisma.workItem.findUnique({ where: { id }, include: { ...include, worklogs: { include: { workType: true, author: { select: { id: true, name: true } } }, orderBy: { occurredAt: 'desc' } } } });
    if (!item) throw new NotFoundException('工作事项不存在');
    return item;
  }

  async create(user: AuthUser, dto: CreateWorkItemDto) {
    this.access.requireInternal(user);
    const ownerId = dto.ownerId ?? user.id;
    if (user.role === 'employee' && ownerId !== user.id) throw new ForbiddenException('普通员工只能为自己创建工作事项');
    await this.validateRelations(dto.workTypeId, dto.organizationId, dto.projectId);
    const { collaboratorIds, startDate, dueDate, ...data } = dto;
    return this.prisma.workItem.create({
      data: {
        ...data,
        ownerId,
        startDate: startDate ? new Date(startDate) : undefined,
        dueDate: dueDate ? new Date(dueDate) : undefined,
        completedAt: dto.status === WorkItemStatus.COMPLETED ? new Date() : undefined,
        progress: dto.status === WorkItemStatus.COMPLETED ? 100 : dto.progress,
        collaborators: collaboratorIds?.length ? { create: [...new Set(collaboratorIds)].filter((id) => id !== ownerId).map((userId) => ({ userId })) } : undefined,
      },
      include,
    });
  }

  async update(user: AuthUser, id: string, dto: UpdateWorkItemDto) {
    const current = await this.access.requireWorkItem(user, id);
    if (current.convertedTicketId) throw new ConflictException('事项已转换，请在关联工单中修改');
    if (user.role === 'employee' && current.ownerId !== user.id) throw new ForbiddenException('只有负责人可以修改此工作事项');
    const ownerId = dto.ownerId ?? current.ownerId;
    if (user.role === 'employee' && ownerId !== user.id) throw new ForbiddenException('普通员工不能转移工作事项');
    await this.validateRelations(dto.workTypeId ?? current.workTypeId, dto.organizationId ?? current.organizationId ?? undefined, dto.projectId ?? current.projectId ?? undefined);
    const { collaboratorIds, startDate, dueDate, ...data } = dto;
    const completed = dto.status === WorkItemStatus.COMPLETED;
    return this.prisma.workItem.update({
      where: { id },
      data: {
        ...data,
        startDate: startDate ? new Date(startDate) : undefined,
        dueDate: dueDate ? new Date(dueDate) : undefined,
        completedAt: completed ? current.completedAt ?? new Date() : dto.status ? null : undefined,
        progress: completed ? 100 : dto.progress,
        collaborators: collaboratorIds ? { deleteMany: {}, create: [...new Set(collaboratorIds)].filter((userId) => userId !== ownerId).map((userId) => ({ userId })) } : undefined,
      },
      include,
    });
  }

  async remove(user: AuthUser, id: string) {
    const current = await this.access.requireWorkItem(user, id);
    if (current.convertedTicketId) throw new ConflictException('事项已转换，保留原始数据用于追溯');
    if (user.role === 'employee' && current.ownerId !== user.id) throw new ForbiddenException('只有负责人可以删除此工作事项');
    await this.prisma.workItem.delete({ where: { id } });
    return { success: true };
  }

  private async validateRelations(workTypeId: string, organizationId?: string, projectId?: string) {
    if (!await this.prisma.workType.findFirst({ where: { id: workTypeId, isActive: true } })) throw new NotFoundException('工作分类不存在或已停用');
    if (organizationId && !await this.prisma.customerOrganization.findUnique({ where: { id: organizationId } })) throw new NotFoundException('客户不存在');
    if (projectId) {
      const project = await this.prisma.project.findUnique({ where: { id: projectId }, select: { organizationId: true } });
      if (!project) throw new NotFoundException('项目不存在');
      if (organizationId && project.organizationId && project.organizationId !== organizationId) throw new ForbiddenException('项目不属于所选客户');
    }
  }
}
