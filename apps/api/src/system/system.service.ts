import { Injectable, NotFoundException } from '@nestjs/common';
import type { Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service.js';
import { UpsertSettingDto } from './dto/setting.dto.js';
import { CreateTeamDto, UpdateTeamDto } from './dto/team.dto.js';

@Injectable()
export class SystemService {
  constructor(private readonly prisma: PrismaService) {}
  roles() { return this.prisma.role.findMany({ include: { permissions: { include: { permission: true } }, _count: { select: { users: true } } }, orderBy: { name: 'asc' } }); }
  teams() { return this.prisma.team.findMany({ include: { members: { include: { user: { select: { id: true, name: true, username: true } } } } }, orderBy: { name: 'asc' } }); }
  createTeam(dto: CreateTeamDto) { return this.prisma.team.create({ data: { name: dto.name, description: dto.description, members: dto.memberIds?.length ? { create: [...new Set(dto.memberIds)].map((userId) => ({ userId })) } : undefined }, include: { members: { include: { user: true } } } }); }
  async updateTeam(id: string, dto: UpdateTeamDto) {
    if (!await this.prisma.team.findUnique({ where: { id } })) throw new NotFoundException('团队不存在');
    return this.prisma.team.update({ where: { id }, data: { name: dto.name, description: dto.description, members: dto.memberIds ? { deleteMany: {}, create: [...new Set(dto.memberIds)].map((userId) => ({ userId })) } : undefined }, include: { members: { include: { user: { select: { id: true, name: true } } } } } });
  }
  async removeTeam(id: string) { await this.prisma.team.delete({ where: { id } }); return { success: true }; }
  settings() { return this.prisma.systemSetting.findMany({ orderBy: { key: 'asc' } }); }
  upsertSetting(dto: UpsertSettingDto) { return this.prisma.systemSetting.upsert({ where: { key: dto.key }, update: { value: dto.value as Prisma.InputJsonValue, isPublic: dto.isPublic }, create: { key: dto.key, value: dto.value as Prisma.InputJsonValue, isPublic: dto.isPublic ?? false } }); }
}

