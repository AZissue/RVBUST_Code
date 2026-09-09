import { Injectable } from '@nestjs/common';
import type { Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service.js';

@Injectable()
export class AuditService {
  constructor(private readonly prisma: PrismaService) {}

  write(data: { actorId?: string; action: string; entityType?: string; entityId?: string; ipAddress?: string; userAgent?: string; metadata?: Prisma.InputJsonValue }) {
    return this.prisma.auditLog.create({ data }).catch((error: unknown) => {
      console.error('Audit write failed', error);
      return null;
    });
  }

  /** 分页列表：20 条/页，按时间倒序 */
  async list(page = 1) {
    const safePage = Math.max(1, Math.min(page, 100000));
    const [total, items] = await this.prisma.$transaction([
      this.prisma.auditLog.count(),
      this.prisma.auditLog.findMany({
        orderBy: { createdAt: 'desc' }, skip: (safePage - 1) * 20, take: 20,
        include: { actor: { select: { id: true, name: true, username: true } } },
      }),
    ]);
    return { items, total, page: safePage, pageSize: 20 };
  }
}

