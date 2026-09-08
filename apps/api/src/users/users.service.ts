import { BadRequestException, ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import type { Prisma, UserStatus } from '@prisma/client';
import { hash } from 'bcryptjs';
import { PrismaService } from '../prisma/prisma.service.js';
import { CreateUserDto } from './dto/create-user.dto.js';
import { ListUsersDto } from './dto/list-users.dto.js';
import { UpdateUserDto } from './dto/update-user.dto.js';
import { zhUserStatus } from '../common/status-labels.js';

const publicUserSelect = {
  id: true, username: true, name: true, email: true, phone: true, department: true, status: true,
  customerOrganizationId: true, createdAt: true, updatedAt: true,
  role: { select: { name: true, label: true } },
} as const;

@Injectable()
export class UsersService {
  constructor(private readonly prisma: PrismaService) {}

  list(query: ListUsersDto = {}) {
    const where: Prisma.UserWhereInput = {
      status: query.status as UserStatus | undefined,
      department: query.department ? { contains: query.department, mode: 'insensitive' } : undefined,
      role: query.role ? { name: query.role } : undefined,
      ...(query.keyword ? { OR: [{ username: { contains: query.keyword, mode: 'insensitive' } }, { name: { contains: query.keyword, mode: 'insensitive' } }] } : {}),
    };
    return this.prisma.user.findMany({ where, select: publicUserSelect, orderBy: { name: 'asc' }, take: 500 });
  }

  assignable() {
    return this.prisma.user.findMany({
      where: { status: 'ACTIVE', role: { name: { in: ['admin', 'support', 'employee'] } } },
      select: { id: true, name: true, role: { select: { name: true } } }, orderBy: { name: 'asc' },
    });
  }

  async create(dto: CreateUserDto) {
    if (dto.role === 'customer' && !dto.customerOrganizationId) throw new BadRequestException('客户账号必须绑定客户公司');
    const role = await this.prisma.role.findUnique({ where: { name: dto.role } });
    if (!role) throw new BadRequestException('角色不存在');
    try {
      return await this.prisma.user.create({
        data: {
          username: dto.username.toLowerCase(), name: dto.name, passwordHash: await hash(dto.password, 12),
          roleId: role.id, email: dto.email || null, phone: dto.phone || null, department: dto.department || null,
          status: 'ACTIVE', customerOrganizationId: dto.customerOrganizationId || null,
        },
        select: publicUserSelect,
      });
    } catch (error) {
      if ((error as { code?: string }).code === 'P2002') throw new ConflictException('用户名或邮箱已存在');
      throw error;
    }
  }

  async update(id: string, dto: UpdateUserDto, actorId: string) {
    const current = await this.prisma.user.findUnique({ where: { id }, include: { role: true } });
    if (!current) throw new NotFoundException('用户不存在');
    const role = dto.role ? await this.prisma.role.findUnique({ where: { name: dto.role } }) : null;
    if (dto.role && !role) throw new BadRequestException('角色不存在');
    const nextRole = dto.role ?? current.role.name;
    if (id === actorId && nextRole !== current.role.name) {
      throw new BadRequestException('不能修改当前登录账号的角色，请由其他管理员操作');
    }
    const nextOrg = dto.customerOrganizationId === undefined ? current.customerOrganizationId : dto.customerOrganizationId;
    if (nextRole === 'customer' && !nextOrg) throw new BadRequestException('客户账号必须绑定客户公司');
    const roleChanged = Boolean(role && role.id !== current.roleId);
    const passwordChanged = Boolean(dto.password);
    return this.prisma.$transaction(async (tx) => {
      const updated = await tx.user.update({
        where: { id },
        data: {
          username: dto.username?.toLowerCase(), name: dto.name, email: dto.email, phone: dto.phone, department: dto.department,
          roleId: role?.id,
          customerOrganizationId: nextRole === 'customer' ? nextOrg : null,
          passwordHash: dto.password ? await hash(dto.password, 12) : undefined,
        },
        select: publicUserSelect,
      });
      // 角色变更或密码重置时吊销该用户全部会话
      if (roleChanged || passwordChanged) await tx.authSession.deleteMany({ where: { userId: id } });
      return updated;
    });
  }

  async approve(id: string) { return this.setStatus(id, 'ACTIVE', 'PENDING'); }
  async reject(id: string) { return this.setStatus(id, 'DISABLED', 'PENDING'); }
  async disable(id: string, actorId: string) {
    if (id === actorId) throw new BadRequestException('不能停用当前登录账号');
    return this.setStatus(id, 'DISABLED', 'ACTIVE');
  }
  async enable(id: string) { return this.setStatus(id, 'ACTIVE', 'DISABLED'); }

  async resetPassword(id: string, password: string) {
    if (!await this.prisma.user.findUnique({ where: { id }, select: { id: true } })) throw new NotFoundException('用户不存在');
    await this.prisma.$transaction([
      this.prisma.user.update({ where: { id }, data: { passwordHash: await hash(password, 12) } }),
      this.prisma.authSession.deleteMany({ where: { userId: id } }),
    ]);
    return { success: true };
  }

  private async setStatus(id: string, next: UserStatus, expected: UserStatus) {
    const current = await this.prisma.user.findUnique({ where: { id }, select: { status: true } });
    if (!current) throw new NotFoundException('用户不存在');
    if (current.status !== expected) throw new BadRequestException(`当前状态为「${zhUserStatus(current.status)}」，不能变更为「${zhUserStatus(next)}」`);
    return this.prisma.$transaction(async (tx) => {
      const changed = await tx.user.updateMany({ where: { id, status: expected }, data: { status: next } });
      if (changed.count !== 1) throw new ConflictException('用户状态已变化，请刷新后重试');
      const updated = await tx.user.findUniqueOrThrow({ where: { id }, select: publicUserSelect });
      // 状态切换时吊销该用户全部会话
      await tx.authSession.deleteMany({ where: { userId: id } });
      return updated;
    });
  }
}
