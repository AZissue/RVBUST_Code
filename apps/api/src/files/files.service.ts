import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { readFile, unlink } from 'node:fs/promises';
import { PHOTO_LIMITS, LoanPhotoDto } from './dto/loan-photo.dto.js';
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

  async registerBug(bugReportId: string, file: Express.Multer.File) {
    const bug = await this.prisma.bugReport.findUnique({ where: { id: bugReportId }, select: { id: true } });
    if (!bug) throw new NotFoundException('BUG 记录不存在');
    return this.prisma.attachment.create({
      data: { bugReportId, storageKey: file.filename, originalName: file.originalname, mimeType: file.mimetype, sizeBytes: file.size, visibility: Visibility.INTERNAL },
    });
  }

  async getForDownload(user: AuthUser, id: string) {
    const attachment = await this.prisma.attachment.findUnique({ where: { id }, include: { loanItem: { include: { loanOrder: true } }, ticket: { select: { id: true } }, repairOrder: { select: { id: true, assigneeId: true, createdById: true } }, bugReport: { select: { id: true } } } });
    if (attachment?.bugReport) return attachment;
    if (attachment?.loanItem) {
      const loan = attachment.loanItem.loanOrder;
      if (user.role === 'customer' || !(user.role === 'admin' || user.role === 'support' || loan.assigneeId === user.id || loan.createdById === user.id)) throw new NotFoundException('附件不存在');
      return attachment;
    }
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

  async registerLoanPhoto(user: AuthUser, itemId: string, file: Express.Multer.File, dto: LoanPhotoDto) {
    let keep = false;
    try {
      const bytes = await readFile(file.path);
      const actual = bytes.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10])) ? 'image/png'
        : bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255 ? 'image/jpeg'
        : bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WEBP' ? 'image/webp' : null;
      if (!actual || actual !== file.mimetype) throw new BadRequestException('仅支持真实的 JPG、PNG、WebP 图片');
      const result = await this.prisma.$transaction(async tx => {
        const item = await tx.loanItem.findUnique({ where: { id: itemId }, include: { loanOrder: true } });
        const loan = item?.loanOrder;
        if (!loan || user.role === 'customer' || !(user.role === 'admin' || user.role === 'support' || loan.assigneeId === user.id || loan.createdById === user.id)) throw new NotFoundException('借测设备不存在');
        // Serialize slot allocation; the unique index and check constraint also enforce the limit.
        await tx.$queryRaw`SELECT id FROM loan_items WHERE id = ${itemId}::uuid FOR UPDATE`;
        const existing = await tx.attachment.findUnique({ where: { photoKey: dto.photoKey } });
        if (existing) {
          if (existing.loanItemId !== itemId || existing.photoCategory !== dto.category) throw new BadRequestException('上传标识已使用');
          return existing;
        }
        const photos = await tx.attachment.findMany({ where: { loanItemId: itemId, photoCategory: dto.category }, select: { photoSlot: true } });
        const slot = Array.from({ length: PHOTO_LIMITS[dto.category] }, (_, i) => i + 1).find(i => !photos.some(p => p.photoSlot === i));
        if (!slot) throw new BadRequestException(`该类图片最多上传 ${PHOTO_LIMITS[dto.category]} 张`);
        return tx.attachment.create({ data: { loanItemId: itemId, photoCategory: dto.category, photoSlot: slot, photoKey: dto.photoKey, storageKey: file.filename, originalName: Buffer.from(file.originalname, 'latin1').toString('utf8'), mimeType: actual, sizeBytes: file.size, visibility: 'INTERNAL' } });
      });
      keep = result.storageKey === file.filename;
      return result;
    } finally { if (!keep) await unlink(file.path).catch(() => {}); }
  }
}
