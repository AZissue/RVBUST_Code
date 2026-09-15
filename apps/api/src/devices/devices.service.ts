import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { DeviceOwnerType, DeviceStatus, type Prisma } from '@prisma/client';
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
      status: query.status,
      ownerType: query.ownerType,
      organizationId: query.organizationId,
      ...(query.model ? { cameraModel: { contains: query.model, mode: 'insensitive' } } : {}),
      ...(query.keyword ? { OR: [{ serialNumber: { contains: query.keyword, mode: 'insensitive' } }, { name: { contains: query.keyword, mode: 'insensitive' } }, { cameraModel: { contains: query.keyword, mode: 'insensitive' } }] } : {}),
    };
    const devices = await this.prisma.device.findMany({ where, include: deviceInclude, orderBy: { updatedAt: 'desc' }, take: 500 });
    const [loanGroups, repairGroups] = await Promise.all([
      this.prisma.loanItem.groupBy({ by: ['deviceId'], where: { deviceId: { in: devices.map(d => d.id) } }, _count: { _all: true } }),
      this.prisma.repairOrder.groupBy({ by: ['deviceId'], where: { deviceId: { in: devices.map(d => d.id) } }, _count: { _all: true } }),
    ]);
    const loanMap = new Map(loanGroups.map(g => [g.deviceId, g._count._all]));
    const repairMap = new Map(repairGroups.map(g => [g.deviceId, g._count._all]));
    return devices.map(d => ({ ...d, health: deviceHealth(loanMap.get(d.id) ?? 0, repairMap.get(d.id) ?? 0) }));
  }

  async get(id: string) {
    const device = await this.prisma.device.findUnique({ where: { id }, include: deviceInclude });
    if (!device) throw new NotFoundException('设备不存在');
    return device;
  }

  async detail(id: string) {
    const device = await this.get(id);
    const orgSelect = { select: { id: true, name: true } } as const;
    const [tickets, loanItems, repairs] = await Promise.all([
      this.prisma.ticket.findMany({ where: { deviceId: id, deletedAt: null }, select: { id: true, number: true, title: true, status: true, createdAt: true, organization: orgSelect }, orderBy: { createdAt: 'desc' } }),
      this.prisma.loanItem.findMany({ where: { deviceId: id }, select: { loanOrder: { select: { id: true, loanNo: true, status: true, loanedAt: true, dueAt: true, createdAt: true, organization: orgSelect } } }, orderBy: { createdAt: 'desc' } }),
      this.prisma.repairOrder.findMany({ where: { deviceId: id }, select: { id: true, repairNo: true, status: true, symptom: true, receivedAt: true, createdAt: true, organization: orgSelect }, orderBy: { createdAt: 'desc' } }),
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

  async remove(id: string) {
    await this.get(id);
    await this.prisma.device.delete({ where: { id } });
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
