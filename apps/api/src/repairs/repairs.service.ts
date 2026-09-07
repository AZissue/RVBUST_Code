import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { RepairStatus, type Prisma } from '@prisma/client';
import { randomInt } from 'node:crypto';
import type { AuthUser } from '../auth/auth.types.js';
import { NotificationsService } from '../notifications/notifications.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { AssignRepairDto, CreateRepairDto, TransitionRepairDto, UpdateRepairDto } from './dto/repair.dto.js';
import { zhStatus } from '../common/status-labels.js';

const repairInclude = {
  device: { select: { id: true, name: true, serialNumber: true, cameraModel: true, status: true, warrantyUntil: true } },
  organization: { select: { id: true, name: true } },
  contact: { select: { id: true, name: true, phone: true } },
  assignee: { select: { id: true, name: true } },
} as const;

// 状态机：RECEIVED→DIAGNOSING→REPAIRING→SHIPPED→CLOSED 单向流转
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
    return this.prisma.$transaction(async (tx) => {
      const device = dto.deviceId
        ? await tx.device.findUnique({ where: { id: dto.deviceId } })
        : dto.serialNumber
          ? await tx.device.findFirst({ where: { serialNumber: dto.serialNumber } })
          : null;
      if (!device) throw new BadRequestException('设备不存在（需提供 deviceId 或 serialNumber）');
      if (device.status === 'REPAIRING' || device.status === 'RETIRED') throw new BadRequestException(`设备当前状态为「${zhStatus(device.status)}」，不能创建返修单`);
      if (!await tx.customerOrganization.findUnique({ where: { id: dto.organizationId }, select: { id: true } })) throw new BadRequestException('客户组织不存在');
      if (dto.contactId && !await tx.contact.findFirst({ where: { id: dto.contactId, organizationId: dto.organizationId }, select: { id: true } })) throw new BadRequestException('联系人不属于该客户');
      const inWarranty = dto.inWarranty ?? (device.warrantyUntil ? device.warrantyUntil >= new Date(new Date().toDateString()) : null);
      const data = {
        deviceId: device.id, organizationId: dto.organizationId, createdById: user.id,
        contactId: dto.contactId || null, symptom: dto.symptom, faultCause: dto.faultCause || null,
        resolution: dto.resolution || null, note: dto.note || null, inWarranty,
        receivedAt: dto.receivedAt ? new Date(dto.receivedAt) : new Date(),
        events: { create: { authorId: user.id, type: 'STATUS_CHANGE', content: '返修单已创建，状态：已收货' } },
      };
      let repair;
      for (let attempt = 0; attempt < 4; attempt++) {
        try { repair = await tx.repairOrder.create({ data: { ...data, repairNo: this.generateNo() }, include: repairInclude }); break; }
        catch (error) { if ((error as { code?: string }).code !== 'P2002' || attempt === 3) throw error; }
      }
      await tx.device.update({ where: { id: device.id }, data: { status: 'REPAIRING' } });
      // 返修确认客户资产：客户资产设备无所属客户时，回填为返修单客户；公司样机保持原归属不动
      if (device.ownerType === 'CUSTOMER' && !device.organizationId) {
        await tx.device.update({ where: { id: device.id }, data: { organizationId: dto.organizationId } });
      }
      return repair;
    });
  }

  async update(user: AuthUser, id: string, dto: UpdateRepairDto) {
    const repair = await this.get(user, id);
    if (repair.status === RepairStatus.CLOSED) throw new BadRequestException('已关闭的返修单不能修改');
    if (dto.contactId && !await this.prisma.contact.findFirst({ where: { id: dto.contactId, organizationId: repair.organizationId }, select: { id: true } })) throw new BadRequestException('联系人不属于该客户');
    return this.prisma.repairOrder.update({
      where: { id },
      data: { symptom: dto.symptom, faultCause: dto.faultCause, resolution: dto.resolution, trackingNo: dto.trackingNo, note: dto.note, inWarranty: dto.inWarranty, contactId: dto.contactId },
      include: repairInclude,
    });
  }

  async transition(user: AuthUser, id: string, dto: TransitionRepairDto) {
    const repair = await this.get(user, id);
    const from = order.indexOf(repair.status);
    const to = order.indexOf(dto.status);
    if (to !== from + 1) throw new BadRequestException(`不允许从「${zhStatus(repair.status)}」变更为「${zhStatus(dto.status)}」，仅支持逐级单向流转`);
    const trackingNo = dto.trackingNo ?? repair.trackingNo;
    if (dto.status === RepairStatus.SHIPPED && !trackingNo) throw new BadRequestException('寄回时必须填写物流单号');
    const now = new Date();
    return this.prisma.$transaction(async (tx) => {
      const updated = await tx.repairOrder.update({
        where: { id },
        data: {
          status: dto.status,
          trackingNo: dto.trackingNo,
          shippedAt: dto.status === RepairStatus.SHIPPED ? now : undefined,
          closedAt: dto.status === RepairStatus.CLOSED ? now : undefined,
        },
        include: repairInclude,
      });
      await tx.repairEvent.create({
        data: { repairOrderId: id, authorId: user.id, type: 'STATUS_CHANGE', content: `状态变更：${statusLabel[repair.status]} → ${statusLabel[dto.status]}${dto.content ? `，${dto.content}` : ''}`, metadata: { from: repair.status, to: dto.status } },
      });
      if (dto.status === RepairStatus.CLOSED) await tx.device.update({ where: { id: repair.deviceId }, data: { status: 'IN_STOCK' } });
      return updated;
    });
  }

  async assign(user: AuthUser, id: string, dto: AssignRepairDto) {
    const repair = await this.get(user, id);
    if (repair.status === RepairStatus.CLOSED) throw new BadRequestException('已关闭的返修单不能指派');
    const assignee = await this.prisma.user.findFirst({ where: { id: dto.assigneeId, status: 'ACTIVE', role: { name: { in: ['admin', 'support', 'employee'] } } } });
    if (!assignee) throw new BadRequestException('被指派者不存在或不是内部成员');
    const updated = await this.prisma.repairOrder.update({ where: { id }, data: { assigneeId: dto.assigneeId }, include: repairInclude });
    await this.notifications.notify({ recipientId: dto.assigneeId, type: 'REPAIR_ASSIGNED', title: '返修单已指派给你', body: `返修单 ${repair.repairNo} 已指派给你跟进。`, dedupeKey: `repair-assign:${repair.id}:${dto.assigneeId}` });
    return updated;
  }

  private generateNo() {
    const date = new Date().toISOString().slice(2, 10).replaceAll('-', '');
    return `RP-${date}${randomInt(0, 1000).toString().padStart(3, '0')}`;
  }
}
