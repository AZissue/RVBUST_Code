import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { BugStatus } from '@prisma/client';
import type { AuthUser } from '../auth/auth.types.js';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';
import { dateSerialPrefix, nextSerial } from '../common/numbering.js';
import { NotificationsService } from '../notifications/notifications.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { CreateBugDto, UpdateBugStatusDto } from './dto/bug.dto.js';

const bugInclude = {
  author: { select: { id: true, name: true } },
  resolver: { select: { id: true, name: true } },
  attachments: { select: { id: true, originalName: true, mimeType: true, sizeBytes: true } },
} as const;

@Injectable()
export class BugsService {
  constructor(private readonly prisma: PrismaService, private readonly notifications: NotificationsService) {}

  async list(user: AuthUser, query: { status?: BugStatus; mine?: boolean }) {
    if (query.status && !Object.values(BugStatus).includes(query.status)) throw new BadRequestException('BUG 状态无效');
    return this.prisma.bugReport.findMany({
      where: { status: query.status, authorId: query.mine ? user.id : undefined },
      include: bugInclude, orderBy: { createdAt: 'desc' }, take: 500,
    });
  }

  async get(id: string) {
    const bug = await this.prisma.bugReport.findUnique({ where: { id }, include: bugInclude });
    if (!bug) throw new NotFoundException('BUG 记录不存在');
    return bug;
  }

  async create(user: AuthUser, dto: CreateBugDto) {
    let bug;
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        const prefix = dateSerialPrefix('BG');
        const last = await this.prisma.bugReport.findFirst({ where: { bugNo: { startsWith: prefix } }, orderBy: { bugNo: 'desc' }, select: { bugNo: true } });
        bug = await this.prisma.bugReport.create({ data: { ...dto, authorId: user.id, bugNo: nextSerial(last?.bugNo ?? null, prefix) }, include: bugInclude });
        break;
      } catch (error) { if ((error as { code?: string }).code !== 'P2002' || attempt === 3) throw error; }
    }
    return bug;
  }

  // 仅管理员调用（controller 层 @Roles('admin')）；标记已修复时记录处理人并通知提交人
  async updateStatus(user: AuthUser, id: string, dto: UpdateBugStatusDto) {
    const bug = await this.get(id);
    if (bug.status === dto.status) return bug;
    const fixed = dto.status === BugStatus.FIXED;
    const updated = await this.prisma.bugReport.update({
      where: { id },
      data: {
        status: dto.status,
        resolverId: fixed ? user.id : null,
        resolvedAt: fixed ? new Date() : null,
      },
      include: bugInclude,
    });
    if (fixed && bug.authorId !== user.id) {
      await this.notifications.notify({
        recipientId: bug.authorId, type: NOTIFICATION_TYPES.BUG_FIXED, severity: 'INFO',
        title: 'BUG 已修复', body: `你提交的 BUG ${bug.bugNo}「${bug.title}」已被标记为已修复。`,
        dedupeKey: `bug-fixed:${bug.id}`,
      });
    }
    return updated;
  }
}
