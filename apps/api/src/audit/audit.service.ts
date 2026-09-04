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

  list() {
    return this.prisma.auditLog.findMany({
      orderBy: { createdAt: 'desc' }, take: 200,
      include: { actor: { select: { id: true, name: true, username: true } } },
    });
  }
}

