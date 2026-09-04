import { Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service.js';
import { CreateNotificationDto } from './dto/create-notification.dto.js';

@Injectable()
export class NotificationsService {
  constructor(private readonly prisma: PrismaService) {}
  list(userId: string) { return this.prisma.notification.findMany({ where: { recipientId: userId }, include: { ticket: { select: { id: true, number: true, title: true } } }, orderBy: { createdAt: 'desc' }, take: 100 }); }
  count(userId: string) { return this.prisma.notification.count({ where: { recipientId: userId, readAt: null } }).then((unread) => ({ unread })); }
  create(dto: CreateNotificationDto) { return this.prisma.notification.create({ data: dto }); }
  async read(userId: string, id: string) {
    const updated = await this.prisma.notification.updateMany({ where: { id, recipientId: userId }, data: { readAt: new Date() } });
    if (!updated.count) throw new NotFoundException('通知不存在');
    return { success: true };
  }
  async readAll(userId: string) { await this.prisma.notification.updateMany({ where: { recipientId: userId, readAt: null }, data: { readAt: new Date() } }); return { success: true }; }
}

