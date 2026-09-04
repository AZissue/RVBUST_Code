import { BadRequestException, ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import { hash } from 'bcryptjs';
import { PrismaService } from '../prisma/prisma.service.js';
import { CreateUserDto } from './dto/create-user.dto.js';
import { UpdateUserDto } from './dto/update-user.dto.js';

const publicUserSelect = {
  id: true, username: true, name: true, email: true, phone: true, isActive: true,
  customerOrganizationId: true, createdAt: true, updatedAt: true,
  role: { select: { name: true, label: true } },
} as const;

@Injectable()
export class UsersService {
  constructor(private readonly prisma: PrismaService) {}

  list() { return this.prisma.user.findMany({ select: publicUserSelect, orderBy: { name: 'asc' } }); }

  assignable() {
    return this.prisma.user.findMany({
      where: { isActive: true, role: { name: { in: ['admin', 'support', 'employee'] } } },
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
          roleId: role.id, email: dto.email || null, phone: dto.phone || null,
          isActive: dto.isActive ?? true, customerOrganizationId: dto.customerOrganizationId || null,
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
    if (id === actorId && dto.isActive === false) throw new BadRequestException('不能停用当前登录账号');
    const role = dto.role ? await this.prisma.role.findUnique({ where: { name: dto.role } }) : null;
    if (dto.role && !role) throw new BadRequestException('角色不存在');
    const nextRole = dto.role ?? current.role.name;
    const nextOrg = dto.customerOrganizationId === undefined ? current.customerOrganizationId : dto.customerOrganizationId;
    if (nextRole === 'customer' && !nextOrg) throw new BadRequestException('客户账号必须绑定客户公司');
    return this.prisma.user.update({
      where: { id },
      data: {
        username: dto.username?.toLowerCase(), name: dto.name, email: dto.email, phone: dto.phone,
        isActive: dto.isActive, roleId: role?.id,
        customerOrganizationId: nextRole === 'customer' ? nextOrg : null,
        passwordHash: dto.password ? await hash(dto.password, 12) : undefined,
      },
      select: publicUserSelect,
    });
  }
}

