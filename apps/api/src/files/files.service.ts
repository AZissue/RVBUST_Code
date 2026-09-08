import { Injectable, NotFoundException } from '@nestjs/common';
import { RepairEventType, Visibility } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';

@Injectable()
export class FilesService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  async register(user: AuthUser, ticketId: string, file: Express.Multer.File, requestedVisibility?: Visibility) {
    await this.access.requireTicket(user, ticketId);
    const visibility = user.role === 'customer' ? Visibility.CUSTOMER : (requestedVisibility ?? Visibility.INTERNAL);
    return this.prisma.$transaction(async (tx) => {
    const attachment = await tx.attachment.create({
      data: { ticketId, storageKey: file.filename, originalName: file.originalname, mimeType: file.mimetype, sizeBytes: file.size, visibility },
    });
    await tx.ticketEvent.create({
      data: { ticketId, authorId: user.id, type: 'ATTACHMENT', visibility, content: `上传附件：${file.originalname}`, metadata: { attachmentId: attachment.id } },
    });
    return attachment;
    });
  }

  async registerRepair(user: AuthUser, repairOrderId: string, file: Express.Multer.File) {
    const repair = await this.prisma.repairOrder.findUnique({ where: { id: repairOrderId }, select: { id: true, assigneeId: true, createdById: true } });
    if (!repair) throw new NotFoundException('返修单不存在');
    const allowed = user.role === 'admin' || user.role === 'support' || repair.assigneeId === user.id || repair.createdById === user.id;
    if (!allowed) throw new NotFoundException('返修单不存在');
    return this.prisma.$transaction(async (tx) => {
    const attachment = await tx.attachment.create({
      data: { repairOrderId, storageKey: file.filename, originalName: file.originalname, mimeType: file.mimetype, sizeBytes: file.size, visibility: Visibility.INTERNAL },
    });
    await tx.repairEvent.create({
      data: { repairOrderId, authorId: user.id, type: RepairEventType.ATTACHMENT, content: `上传附件：${file.originalname}`, metadata: { attachmentId: attachment.id } },
    });
    return attachment;
    });
  }

  async getForDownload(user: AuthUser, id: string) {
    const attachment = await this.prisma.attachment.findUnique({ where: { id }, include: { ticket: { select: { id: true } }, repairOrder: { select: { id: true, assigneeId: true, createdById: true } } } });
    if (attachment?.ticket) {
      await this.access.requireTicket(user, attachment.ticket.id);
      if (user.role === 'customer' && attachment.visibility !== Visibility.CUSTOMER) throw new NotFoundException('附件不存在');
      return attachment;
    }
    if (attachment?.repairOrder) {
      const repair = attachment.repairOrder;
      const allowed = user.role === 'admin' || user.role === 'support' || repair.assigneeId === user.id || repair.createdById === user.id;
      if (!allowed) throw new NotFoundException('附件不存在');
      return attachment;
    }
    throw new NotFoundException('附件不存在');
  }
}
