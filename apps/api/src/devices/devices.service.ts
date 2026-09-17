import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { DeviceOwnerType, DeviceStatus, type Prisma } from '@prisma/client';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { ChangeDeviceStatusDto, CreateDeviceDto, UpdateDeviceDto } from './dto/device.dto.js';
import { deviceHealth } from './device-health.js';
import { zhStatus } from '../common/status-labels.js';

const deviceInclude = { organization: { select: { id: true, name: true } } } as const;

// 状态机：IN_STOCK↔LOANED↔REPAIRING 链式互转；RETIRED 可从任意状态进入且不可恢复
const transitions: Record<DeviceStatus, DeviceStatus[]> = {
  IN_STOCK: [DeviceStatus.LOANED, DeviceStatus.RETIRED],
  LOANED: [DeviceStatus.IN_STOCK, DeviceStatus.REPAIRING, DeviceStatus.RETIRED],
  REPAIRING: [DeviceStatus.LOANED, DeviceStatus.RETIRED],
  RETIRED: [],
};

@Injectable()
export class DevicesService {
  constructor(private readonly prisma: PrismaService) {}

  async list(query: { status?: DeviceStatus; ownerType?: DeviceOwnerType; organizationId?: string; model?: string; keyword?: string }) {
    if (query.status && !Object.values(DeviceStatus).includes(query.status)) throw new BadRequestException('设备状态无效');
    if (query.ownerType && !Object.values(DeviceOwnerType).includes(query.ownerType)) throw new BadRequestException('设备归属无效');
    const where: Prisma.DeviceWhereInput = {
      deletedAt: null,
      status: query.status,
      ownerType: query.ownerType,
      organizationId: query.organizationId,
      ...(query.model ? { cameraModel: { contains: query.model, mode: 'insensitive' } } : {}),
      ...(query.keyword ? { OR: [{ serialNumber: { contains: query.keyword, mode: 'insensitive' } }, { name: { contains: query.keyword, mode: 'insensitive' } }, { cameraModel: { contains: query.keyword, mode: 'insensitive' } }] } : {}),
    };
    const devices = await this.prisma.device.findMany({ where, include: deviceInclude, orderBy: { updatedAt: 'desc' }, take: 500 });
    const [loanGroups, repairGroups] = await Promise.all([
      this.prisma.loanItem.groupBy({ by: ['deviceId'], where: { deviceId: { in: devices.map(d => d.id) }, loanOrder: { deletedAt: null } }, _count: { _all: true } }),
      this.prisma.repairOrder.groupBy({ by: ['deviceId'], where: { deviceId: { in: devices.map(d => d.id) }, deletedAt: null }, _count: { _all: true } }),
    ]);
    const loanMap = new Map(loanGroups.map(g => [g.deviceId, g._count._all]));
    const repairMap = new Map(repairGroups.map(g => [g.deviceId, g._count._all]));
    return devices.map(d => {
      const loanCount = loanMap.get(d.id) ?? 0;
      const repairCount = repairMap.get(d.id) ?? 0;
      return { ...d, loanCount, repairCount, health: deviceHealth(loanCount, repairCount) };
    });
  }

  async get(id: string) {
    const device = await this.prisma.device.findFirst({ where: { id, deletedAt: null }, include: deviceInclude });
    if (!device) throw new NotFoundException('设备不存在');
    return device;
  }

  async detail(id: string) {
    const device = await this.get(id);
    const orgSelect = { select: { id: true, name: true } } as const;
    const [tickets, loanItems, repairs] = await Promise.all([
      this.prisma.ticket.findMany({ where: { deviceId: id, deletedAt: null }, select: { id: true, number: true, title: true, status: true, createdAt: true, organization: orgSelect }, orderBy: { createdAt: 'desc' } }),
      this.prisma.loanItem.findMany({ where: { deviceId: id, loanOrder: { deletedAt: null } }, select: { loanOrder: { select: { id: true, loanNo: true, status: true, loanedAt: true, dueAt: true, createdAt: true, organization: orgSelect } } }, orderBy: { createdAt: 'desc' } }),
      this.prisma.repairOrder.findMany({ where: { deviceId: id, deletedAt: null }, select: { id: true, repairNo: true, status: true, symptom: true, receivedAt: true, createdAt: true, organization: orgSelect }, orderBy: { createdAt: 'desc' } }),
    ]);
    const history = [
      ...tickets.map(t => ({ kind: 'ticket' as const, id: t.id, number: t.number, title: t.title, status: t.status, customerName: t.organization?.name ?? '', date: t.createdAt, href: `/tickets/${t.id}` })),
      ...loanItems.map(l => { const o = l.loanOrder; return { kind: 'loan' as const, id: o.id, number: o.loanNo, title: '设备借测', status: o.status, customerName: o.organization?.name ?? '', date: o.loanedAt ?? o.createdAt, dueAt: o.dueAt, href: '' }; }),
      ...repairs.map(r => ({ kind: 'repair' as const, id: r.id, number: r.repairNo, title: r.symptom, status: r.status, customerName: r.organization?.name ?? '', date: r.receivedAt ?? r.createdAt, href: '' })),
    ].sort((a, b) => b.date.getTime() - a.date.getTime()).slice(0, 50);
    const chain: { name: string; count: number }[] = [];
    [...history].sort((a, b) => a.date.getTime() - b.date.getTime()).forEach(h => {
      if (!h.customerName) return;
      const tail = chain[chain.length - 1];
      if (tail && tail.name === h.customerName) tail.count += 1;
      else chain.push({ name: h.customerName, count: 1 });
    });
    const customerIds = new Set<string>();
    if (device.organizationId) customerIds.add(device.organizationId);
    tickets.forEach(t => t.organization && customerIds.add(t.organization.id));
    loanItems.forEach(l => l.loanOrder.organization && customerIds.add(l.loanOrder.organization.id));
    repairs.forEach(r => r.organization && customerIds.add(r.organization.id));
    const loanCount = loanItems.length;
    const repairCount = repairs.length;
    return {
      device,
      stats: { loanCount, repairCount, customerCount: customerIds.size, health: deviceHealth(loanCount, repairCount) },
      chain,
      history,
    };
  }

  async create(dto: CreateDeviceDto) {
    const ownerType = dto.ownerType ?? DeviceOwnerType.CUSTOMER;
    if (ownerType === DeviceOwnerType.CUSTOMER && !dto.organizationId) throw new BadRequestException('客户资产必须选择所属客户');
    if (dto.organizationId && !await this.prisma.customerOrganization.findUnique({ where: { id: dto.organizationId }, select: { id: true } })) {
      throw new BadRequestException('所属客户组织不存在');
    }
    return this.prisma.device.create({ data: this.clean(dto), include: deviceInclude });
  }

  async update(id: string, dto: UpdateDeviceDto) {
    const device = await this.get(id);
    const ownerType = dto.ownerType ?? device.ownerType;
    const organizationId = dto.organizationId !== undefined ? dto.organizationId : device.organizationId;
    if (ownerType === DeviceOwnerType.CUSTOMER && !organizationId) throw new BadRequestException('客户资产必须选择所属客户');
    if (organizationId && !await this.prisma.customerOrganization.findUnique({ where: { id: organizationId }, select: { id: true } })) {
      throw new BadRequestException('所属客户组织不存在');
    }
    return this.prisma.device.update({ where: { id }, data: this.clean(dto), include: deviceInclude });
  }

  async changeStatus(id: string, dto: ChangeDeviceStatusDto) {
    const device = await this.get(id);
    if (!transitions[device.status].includes(dto.status)) {
      throw new BadRequestException(`不允许从「${zhStatus(device.status)}」变更为「${zhStatus(dto.status)}」`);
    }
    return this.prisma.device.update({ where: { id }, data: { status: dto.status }, include: deviceInclude });
  }

  /** 移入回收站（软删除）：保留台账与关联历史，可在回收站恢复 */
  async softDelete(user: AuthUser, id: string) {
    const device = await this.get(id);
    return this.prisma.$transaction(async (tx) => {
      await tx.device.update({ where: { id }, data: { deletedAt: new Date(), deletedById: user.id } });
      await tx.auditLog.create({ data: { actorId: user.id, action: 'device.delete', entityType: 'Device', entityId: id, metadata: { name: device.name, serialNumber: device.serialNumber } } });
      return { success: true };
    });
  }

  /** 回收站列表（仅已删除设备） */
  async listDeleted() {
    return this.prisma.device.findMany({
      where: { deletedAt: { not: null } },
      include: { ...deviceInclude, deletedBy: { select: { id: true, name: true } } },
      orderBy: { deletedAt: 'desc' },
      take: 200,
    });
  }

  /** 从回收站恢复 */
  async restore(user: AuthUser, id: string) {
    const device = await this.prisma.device.findUnique({ where: { id }, select: { deletedAt: true } });
    if (!device) throw new NotFoundException('设备不存在');
    if (!device.deletedAt) throw new BadRequestException('设备不在回收站中');
    return this.prisma.$transaction(async (tx) => {
      await tx.device.update({ where: { id }, data: { deletedAt: null, deletedById: null } });
      await tx.auditLog.create({ data: { actorId: user.id, action: 'device.restore', entityType: 'Device', entityId: id } });
      return { success: true };
    });
  }

  /** 彻底删除回收站中的设备（仅管理员）：存在工单/借测/返修引用时拒绝，避免断开追溯 */
  async purge(user: AuthUser, id: string) {
    const device = await this.prisma.device.findUnique({ where: { id }, select: { deletedAt: true, name: true } });
    if (!device) throw new NotFoundException('设备不存在');
    if (!device.deletedAt) throw new BadRequestException('仅回收站中的设备可以彻底删除');
    const [tickets, loanItems, repairs] = await Promise.all([
      this.prisma.ticket.count({ where: { deviceId: id } }),
      this.prisma.loanItem.count({ where: { deviceId: id } }),
      this.prisma.repairOrder.count({ where: { deviceId: id } }),
    ]);
    if (tickets || loanItems || repairs) {
      throw new BadRequestException(`该设备仍存在 ${[tickets ? `${tickets} 张工单` : '', loanItems ? `${loanItems} 条借测记录` : '', repairs ? `${repairs} 条返修记录` : ''].filter(Boolean).join('、')}引用，不能彻底删除`);
    }
    await this.prisma.$transaction(async (tx) => {
      await tx.device.delete({ where: { id } });
      await tx.auditLog.create({ data: { actorId: user.id, action: 'device.purge', entityType: 'Device', entityId: id, metadata: { name: device.name } } });
    });
    return { success: true };
  }

  private clean<T extends CreateDeviceDto | UpdateDeviceDto>(dto: T): Prisma.DeviceUncheckedCreateInput {
    const { organizationId, purchaseDate, warrantyUntil, ...rest } = dto;
    return {
      ...rest,
      organizationId,
      purchaseDate: purchaseDate ? new Date(purchaseDate) : undefined,
      warrantyUntil: warrantyUntil ? new Date(warrantyUntil) : undefined,
    } as Prisma.DeviceUncheckedCreateInput;
  }
}
