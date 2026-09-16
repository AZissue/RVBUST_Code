import { Injectable, Logger } from '@nestjs/common';
import type { NotificationSeverity } from '@prisma/client';
import { NotificationsService } from '../notifications/notifications.service.js';
import { PrismaService } from '../prisma/prisma.service.js';

interface LinkageNotifyInput {
  recipientId: string;
  ticketId?: string | null;
  type: string;
  severity?: NotificationSeverity;
  title: string;
  body: string;
  /** 去重前缀：含单据/工单标识，不含时间戳（存储时会追加时间戳保证唯一约束不冲突） */
  dedupeKey: string;
}

/** 联动通知的接收人解析与去重发送：工单负责人（无则创建人兜底）、admin 列表、未读去重、时间窗去重 */
@Injectable()
export class LinkageNotifyService {
  private readonly logger = new Logger(LinkageNotifyService.name);

  constructor(private readonly prisma: PrismaService, private readonly notifications: NotificationsService) {}

  /** 工单负责人；无负责人退化为工单创建人 */
  async ticketOwnerId(ticketId: string): Promise<string | null> {
    const ticket = await this.prisma.ticket.findUnique({ where: { id: ticketId }, select: { assigneeId: true, createdById: true } });
    return ticket ? (ticket.assigneeId ?? ticket.createdById) : null;
  }

  /** 所有 ACTIVE 的管理员 */
  async adminIds(): Promise<string[]> {
    const admins = await this.prisma.user.findMany({ where: { status: 'ACTIVE', role: { name: 'admin' } }, select: { id: true } });
    return admins.map((admin) => admin.id);
  }

  /**
   * 同一单据同一时机只通知一次：该用户已存在同 dedupeKey 前缀的未读通知则跳过；
   * 已读之后再次触发会生成新通知（重提醒）。
   */
  async notifyUnreadOnce(input: LinkageNotifyInput): Promise<void> {
    const unread = await this.prisma.notification.findFirst({
      where: { recipientId: input.recipientId, dedupeKey: { startsWith: input.dedupeKey }, readAt: null },
      select: { id: true },
    });
    if (unread) return;
    await this.notifications.create({ ...input, ticketId: input.ticketId ?? undefined, dedupeKey: `${input.dedupeKey}:${Date.now()}` });
  }

  /** 时间窗去重（cron 用）：该用户在 since 之后已收到同前缀同类型通知则返回 true */
  async hasNotifiedSince(recipientId: string, type: string, dedupeKeyPrefix: string, since: Date): Promise<boolean> {
    const found = await this.prisma.notification.findFirst({
      where: { recipientId, type, dedupeKey: { startsWith: dedupeKeyPrefix }, createdAt: { gte: since } },
      select: { id: true },
    });
    return Boolean(found);
  }

  /** 包装 notifyUnreadOnce：通知发送失败只记日志，不影响事件主流程 */
  async safeNotifyUnreadOnce(input: LinkageNotifyInput): Promise<void> {
    try {
      await this.notifyUnreadOnce(input);
    } catch (error) {
      this.logger.error(`联动通知发送失败（${input.type} → ${input.recipientId}）`, error instanceof Error ? error.stack : String(error));
    }
  }
}
