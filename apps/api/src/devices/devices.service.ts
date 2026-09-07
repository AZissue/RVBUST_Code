import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { DeviceStatus, type Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service.js';
import { ChangeDeviceStatusDto, CreateDeviceDto, UpdateDeviceDto } from './dto/device.dto.js';
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

  list(query: { status?: DeviceStatus; organizationId?: string; model?: string; keyword?: string }) {
    if (query.status && !Object.values(DeviceStatus).includes(query.status)) throw new BadRequestException('设备状态无效');
    const where: Prisma.DeviceWhereInput = {
      status: query.status,
      organizationId: query.organizationId,
      ...(query.model ? { cameraModel: { contains: query.model, mode: 'insensitive' } } : {}),
      ...(query.keyword ? { OR: [{ serialNumber: { contains: query.keyword, mode: 'insensitive' } }, { name: { contains: query.keyword, mode: 'insensitive' } }, { cameraModel: { contains: query.keyword, mode: 'insensitive' } }] } : {}),
    };
    return this.prisma.device.findMany({ where, include: deviceInclude, orderBy: { updatedAt: 'desc' }, take: 500 });
  }

  async get(id: string) {
    const device = await this.prisma.device.findUnique({ where: { id }, include: deviceInclude });
    if (!device) throw new NotFoundException('设备不存在');
    return device;
  }

  async create(dto: CreateDeviceDto) {
    if (!await this.prisma.customerOrganization.findUnique({ where: { id: dto.organizationId }, select: { id: true } })) {
      throw new BadRequestException('所属客户组织不存在');
    }
    return this.prisma.device.create({ data: this.clean(dto), include: deviceInclude });
  }

  async update(id: string, dto: UpdateDeviceDto) {
    await this.get(id);
    if (dto.organizationId && !await this.prisma.customerOrganization.findUnique({ where: { id: dto.organizationId }, select: { id: true } })) {
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
      organizationId: organizationId as string,
      purchaseDate: purchaseDate ? new Date(purchaseDate) : undefined,
      warrantyUntil: warrantyUntil ? new Date(warrantyUntil) : undefined,
    } as Prisma.DeviceUncheckedCreateInput;
  }
}
