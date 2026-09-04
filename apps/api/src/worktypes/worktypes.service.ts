import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service.js';
import { CreateWorkTypeDto, UpdateWorkTypeDto } from './dto/work-type.dto.js';

@Injectable()
export class WorktypesService {
  constructor(private readonly prisma: PrismaService) {}
  list(activeOnly = true) { return this.prisma.workType.findMany({ where: activeOnly ? { isActive: true } : {}, orderBy: [{ sortOrder: 'asc' }, { label: 'asc' }] }); }
  create(dto: CreateWorkTypeDto) { return this.prisma.workType.create({ data: dto }); }
  async update(id: string, dto: UpdateWorkTypeDto) {
    if (!await this.prisma.workType.findUnique({ where: { id } })) throw new NotFoundException('工作分类不存在');
    return this.prisma.workType.update({ where: { id }, data: dto });
  }
}
