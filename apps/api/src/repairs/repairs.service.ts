import { BadRequestException, ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import { RepairEventType, RepairStatus, type Prisma } from '@prisma/client';
import type { AuthUser } from '../auth/auth.types.js';
import { NotificationsService } from '../notifications/notifications.service.js';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';
import { dateSerialPrefix, nextSerial } from '../common/numbering.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { AssignRepairDto, CreateRepairDto, TransitionRepairDto, UpdateRepairDto } from './dto/repair.dto.js';
import { zhStatus } from '../common/status-labels.js';
import { createReturnPdf } from './return-pdf.js';
import type { ReturnFormDto } from './dto/return-form.dto.js';
import { mkdir, writeFile, unlink } from 'node:fs/promises';
import { resolve } from 'node:path';
import { randomUUID } from 'node:crypto';

const repairInclude = {
  device: { select: { id: true, name: true, serialNumber: true, cameraModel: true, status: true, warrantyUntil: true } },
  organization: { select: { id: true, name: true } },
  contact: { select: { id: true, name: true, phone: true } },
  assignee: { select: { id: true, name: true } },
} as const;

// 非顺序调整需要原因，所有变更保留历史。
const order: RepairStatus[] = [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING, RepairStatus.SHIPPED, RepairStatus.CLOSED];
const statusLabel: Record<RepairStatus, string> = { RECEIVED: '已收货', DIAGNOSING: '诊断中', REPAIRING: '维修中', SHIPPED: '已寄回', CLOSED: '已关闭' };

@Injectable()
export class RepairsService {
  constructor(private readonly prisma: PrismaService, private readonly notifications: NotificationsService) {}

  private scopeWhere(user: AuthUser): Prisma.RepairOrderWhereInput {
    if (user.role === 'employee') return { OR: [{ assigneeId: user.id }, { createdById: user.id }] };
    return {};
  }

  private requireInternal(user: AuthUser) {
    if (user.role === 'customer') throw new BadRequestException('客户账号不能访问返修单');
  }

  list(user: AuthUser, query: { status?: RepairStatus; organizationId?: string; assigneeId?: string; mine?: boolean }) {
    this.requireInternal(user);
    if (query.status && !Object.values(RepairStatus).includes(query.status)) throw new BadRequestException('返修单状态无效');
    return this.prisma.repairOrder.findMany({
      where: { AND: [this.scopeWhere(user)], status: query.status, organizationId: query.organizationId, assigneeId: query.mine ? user.id : query.assigneeId },
      include: repairInclude, orderBy: { updatedAt: 'desc' }, take: 500,
    });
  }

  async get(user: AuthUser, id: string) {
    this.requireInternal(user);
    const repair = await this.prisma.repairOrder.findFirst({
      where: { id, AND: [this.scopeWhere(user)] },
      include: { ...repairInclude, events: { orderBy: { createdAt: 'asc' } }, attachments: true },
    });
    if (!repair) throw new NotFoundException('返修单不存在');
    return repair;
  }

  async create(user: AuthUser, dto: CreateRepairDto) {
    if (dto.manualSerialNumber && dto.deviceId) throw new BadRequestException('手动填写模式不能同时关联设备');
    const manualSN = dto.serialNumber?.trim();
    if (dto.manualSerialNumber && !manualSN) throw new BadRequestException('请填写序列号');
    return this.prisma.$transaction(async (tx) => {
      const device = dto.manualSerialNumber ? null : dto.deviceId
        ? await tx.device.findUnique({ where: { id: dto.deviceId } })
        : dto.serialNumber
          // 序列号建单：匹配本客户或尚未归属客户的设备（无归属客户资产在创建返修单时回填归属）
          ? await tx.device.findFirst({ where: { serialNumber: dto.serialNumber, OR: [{ organizationId: dto.organizationId }, { organizationId: null }] } })
          : null;
      if (!device && !dto.manualSerialNumber) throw new BadRequestException('设备不存在，请选择已有设备或使用手动填写模式');
      const serialNumber = dto.manualSerialNumber ? manualSN : device?.serialNumber;
      if (dto.returnForm && dto.returnForm.serialNumber.trim() !== serialNumber?.trim()) throw new BadRequestException('返厂单 SN 与所选序列号不一致');
      if (device && (device.status === 'REPAIRING' || device.status === 'RETIRED')) throw new BadRequestException(`设备当前状态为「${zhStatus(device.status)}」，不能创建返修单`);
      if (!await tx.customerOrganization.findUnique({ where: { id: dto.organizationId }, select: { id: true } })) throw new BadRequestException('客户组织不存在');
      if (dto.contactId && !await tx.contact.findFirst({ where: { id: dto.contactId, organizationId: dto.organizationId }, select: { id: true } })) throw new BadRequestException('联系人不属于该客户');
      const inWarranty = dto.inWarranty ?? (device?.warrantyUntil ? device.warrantyUntil >= new Date(new Date().toDateString()) : null);
      const data = {
        returnForm: dto.returnForm ? { ...dto.returnForm } : undefined,
        deviceId: device?.id ?? null, serialNumber, organizationId: dto.organizationId, createdById: user.id,
        contactId: dto.contactId || null, symptom: dto.symptom, faultCause: dto.faultCause || null,
        resolution: dto.resolution || null, note: dto.note || null, inWarranty,
        receivedAt: dto.receivedAt ? new Date(dto.receivedAt) : new Date(),
        events: { create: { authorId: user.id, type: RepairEventType.STATUS_CHANGE, content: '返修单已创建，状态：已收货' } },
      };
      let repair;
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
          const prefix = dateSerialPrefix('RP');
          const last = await tx.repairOrder.findFirst({ where: { repairNo: { startsWith: prefix } }, orderBy: { repairNo: 'desc' }, select: { repairNo: true } });
          repair = await tx.repairOrder.create({ data: { ...data, repairNo: nextSerial(last?.repairNo ?? null, prefix) }, include: repairInclude }); break;
        }
        catch (error) { if ((error as { code?: string }).code !== 'P2002' || attempt === 3) throw error; }
      }
      if (device) await tx.device.update({ where: { id: device.id }, data: { status: 'REPAIRING' } });
      // 返修确认客户资产：客户资产设备无所属客户时，回填为返修单客户；公司样机保持原归属不动
      if (device?.ownerType === 'CUSTOMER' && !device.organizationId) {
        await tx.device.update({ where: { id: device.id }, data: { organizationId: dto.organizationId } });
      }
      return repair;
    });
  }

  async exportPdf(user: AuthUser, id: string) {
    const repair = await this.get(user, id);
    if (!repair.returnForm) throw new BadRequestException('请先补全并保存返厂表单');
    const bytes = await createReturnPdf(repair.returnForm as unknown as ReturnFormDto, repair.symptom, repair.repairNo);
    const root = resolve(process.env.UPLOAD_DIR ?? './uploads');
    await mkdir(root, { recursive: true });
    const storageKey = `${randomUUID()}.pdf`;
    const path = resolve(root, storageKey);
    await writeFile(path, bytes, { flag: 'wx' });
    try {
      return await this.prisma.$transaction(async tx => {
        const attachment = await tx.attachment.create({ data: { repairOrderId: id, storageKey, originalName: `${repair.repairNo}-返厂维修单.pdf`, mimeType: 'application/pdf', sizeBytes: bytes.length, visibility: 'INTERNAL' } });
        await tx.repairEvent.create({ data: { repairOrderId: id, authorId: user.id, type: 'ATTACHMENT', content: '生成并归档返厂维修单 PDF', metadata: { attachmentId: attachment.id, sourceUpdatedAt: repair.updatedAt.toISOString() } } });
        return attachment;
      });
    } catch (error) { await unlink(path).catch(() => {}); throw error; }
  }

  async update(user: AuthUser, id: string, dto: UpdateRepairDto) {
    const repair = await this.get(user, id);
    if (repair.device && dto.returnForm && dto.returnForm.serialNumber.trim() !== repair.device.serialNumber?.trim()) throw new BadRequestException('返厂单 SN 与关联设备不一致');
    if (dto.contactId && !await this.prisma.contact.findFirst({ where: { id: dto.contactId, organizationId: repair.organizationId }, select: { id: true } })) throw new BadRequestException('联系人不属于该客户');
    return this.prisma.repairOrder.update({
      where: { id },
      data: { serialNumber: dto.returnForm?.serialNumber.trim(), returnForm: dto.returnForm ? { ...dto.returnForm } : undefined, symptom: dto.symptom, faultCause: dto.faultCause, resolution: dto.resolution, trackingNo: dto.trackingNo, note: dto.note, inWarranty: dto.inWarranty, contactId: dto.contactId },
      include: repairInclude,
    });
  }

  async transition(user: AuthUser, id: string, dto: TransitionRepairDto) {
    const repair = await this.get(user, id);
    if (dto.expectedStatus && dto.expectedStatus !== repair.status) throw new ConflictException('状态已被其他人修改，请刷新后重试');
    const from = order.indexOf(repair.status);
    const to = order.indexOf(dto.status);
    if (to === from) throw new BadRequestException('请选择不同的状态');
    if (to !== from + 1 && !dto.content?.trim()) throw new BadRequestException('回退或跳转状态时请填写调整原因');
    const trackingNo = dto.trackingNo ?? repair.trackingNo;
    if (dto.status === RepairStatus.SHIPPED && !trackingNo) throw new BadRequestException('寄回时必须填写物流单号');
    const now = new Date();
    return this.prisma.$transaction(async (tx) => {
      if (repair.deviceId) {
        await tx.$queryRaw`SELECT id FROM devices WHERE id = ${repair.deviceId}::uuid FOR UPDATE`;
        const device = await tx.device.findUniqueOrThrow({ where: { id: repair.deviceId } });
        const other = await tx.repairOrder.count({ where: { deviceId: repair.deviceId, id: { not: id }, status: { not: RepairStatus.CLOSED } } });
        if (dto.status !== RepairStatus.CLOSED && (other || ['LOANED', 'RETIRED'].includes(device.status))) throw new BadRequestException('设备已借出、报废或存在其他未关闭返修单，不能回退；请先处理设备当前业务');
        if (dto.status !== RepairStatus.CLOSED) await tx.device.update({ where: { id: device.id }, data: { status: 'REPAIRING' } });
        else if (!other && device.status === 'REPAIRING') await tx.device.update({ where: { id: device.id }, data: { status: 'IN_STOCK' } });
      }
      const changed = await tx.repairOrder.updateMany({
        where: { id, status: repair.status, updatedAt: repair.updatedAt },
        data: {
          status: dto.status,
          trackingNo: dto.trackingNo,
          shippedAt: to < order.indexOf(RepairStatus.SHIPPED) ? null : dto.status === RepairStatus.SHIPPED ? now : undefined,
          closedAt: dto.status === RepairStatus.CLOSED ? now : null,
        },
      });
      if (changed.count !== 1) throw new ConflictException('返修单已被其他人修改，请刷新后重试');
      await tx.repairEvent.create({
        data: { repairOrderId: id, authorId: user.id, type: RepairEventType.STATUS_CHANGE, content: `${user.name} 修改状态：${statusLabel[repair.status]} → ${statusLabel[dto.status]}${dto.content ? `，${dto.content.trim()}` : ''}`, metadata: { from: repair.status, to: dto.status } },
      });
      return tx.repairOrder.findUniqueOrThrow({ where: { id }, include: repairInclude });
    });
  }

  async assign(user: AuthUser, id: string, dto: AssignRepairDto) {
    const repair = await this.get(user, id);
    const assignee = await this.prisma.user.findFirst({ where: { id: dto.assigneeId, status: 'ACTIVE', role: { name: { in: ['admin', 'support', 'employee'] } } } });
    if (!assignee) throw new BadRequestException('被指派者不存在或不是内部成员');
    const updated = await this.prisma.repairOrder.update({ where: { id }, data: { assigneeId: dto.assigneeId }, include: repairInclude });
    await this.notifications.notify({ recipientId: dto.assigneeId, type: NOTIFICATION_TYPES.REPAIR_ASSIGNED, title: '返修单已指派给你', body: `返修单 ${repair.repairNo} 已指派给你跟进。`, dedupeKey: `repair-assign:${repair.id}:${dto.assigneeId}` });
    return updated;
  }
}
