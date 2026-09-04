import { Injectable, NotFoundException } from '@nestjs/common';
import { Visibility } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';

@Injectable()
export class FilesService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  async register(user: AuthUser, ticketId: string, file: Express.Multer.File, requestedVisibility?: Visibility) {
    await this.access.requireTicket(user, ticketId);
    const visibility = user.role === 'customer' ? Visibility.CUSTOMER : (requestedVisibility ?? Visibility.INTERNAL);
    const attachment = await this.prisma.attachment.create({
      data: { ticketId, storageKey: file.filename, originalName: file.originalname, mimeType: file.mimetype, sizeBytes: file.size, visibility },
    });
    await this.prisma.ticketEvent.create({
      data: { ticketId, authorId: user.id, type: 'ATTACHMENT', visibility, content: `上传附件：${file.originalname}`, metadata: { attachmentId: attachment.id } },
    });
    return attachment;
  }

  async getForDownload(user: AuthUser, id: string) {
    const attachment = await this.prisma.attachment.findUnique({ where: { id }, include: { ticket: { select: { id: true } } } });
    if (!attachment?.ticket) throw new NotFoundException('附件不存在');
    await this.access.requireTicket(user, attachment.ticket.id);
    if (user.role === 'customer' && attachment.visibility !== Visibility.CUSTOMER) throw new NotFoundException('附件不存在');
    return attachment;
  }
}

