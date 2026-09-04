import { ConflictException, Injectable, NotFoundException } from '@nestjs/common';
import type { Prisma } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { CreateContactDto, UpdateContactDto } from './dto/contact.dto.js';
import { CreateCustomerDto, UpdateCustomerDto } from './dto/customer.dto.js';
import { CreateDeviceDto, UpdateDeviceDto } from './dto/device.dto.js';
import { CreateProjectDto, UpdateProjectDto } from './dto/project.dto.js';

const detailInclude = {
  technicalOwner: { select: { id: true, name: true } },
  businessOwner: { select: { id: true, name: true } },
  contacts: { orderBy: [{ isPrimary: 'desc' }, { name: 'asc' }] },
  devices: { orderBy: { createdAt: 'desc' } },
  projects: { orderBy: { updatedAt: 'desc' } },
  _count: { select: { tickets: true } },
} satisfies Prisma.CustomerOrganizationInclude;

@Injectable()
export class CustomersService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService) {}

  list(user: AuthUser, search?: string) {
    return this.prisma.customerOrganization.findMany({
      where: {
        ...this.access.customerWhere(user),
        ...(search ? { OR: [{ name: { contains: search, mode: 'insensitive' } }, { industry: { contains: search, mode: 'insensitive' } }] } : {}),
      },
      include: { contacts: { where: { isPrimary: true }, take: 1 }, _count: { select: { devices: true, projects: true, tickets: true } } },
      orderBy: { updatedAt: 'desc' },
    });
  }

  async get(user: AuthUser, id: string) {
    await this.access.requireCustomer(user, id);
    return this.prisma.customerOrganization.findUnique({ where: { id }, include: detailInclude });
  }

  listDevices(user: AuthUser) {
    return this.prisma.device.findMany({
      where: { organization: this.access.customerWhere(user) },
      include: { organization: { select: { id: true, name: true } } },
      orderBy: { updatedAt: 'desc' },
    });
  }

  listProjects() {
    return this.prisma.project.findMany({ include: { organization: { select: { id: true, name: true } } }, orderBy: { updatedAt: 'desc' } });
  }

  async create(dto: CreateCustomerDto) {
    try { return await this.prisma.customerOrganization.create({ data: this.clean(dto), include: detailInclude }); }
    catch (error) { if ((error as { code?: string }).code === 'P2002') throw new ConflictException('客户公司名称已存在'); throw error; }
  }

  async update(id: string, dto: UpdateCustomerDto) {
    await this.ensureExists(id);
    return this.prisma.customerOrganization.update({ where: { id }, data: this.clean(dto), include: detailInclude });
  }

  async remove(id: string) {
    await this.ensureExists(id);
    try { await this.prisma.customerOrganization.delete({ where: { id } }); return { success: true }; }
    catch (error) { if ((error as { code?: string }).code === 'P2003') throw new ConflictException('客户仍有关联工单或账号，不能删除'); throw error; }
  }

  async addContact(organizationId: string, dto: CreateContactDto) {
    await this.ensureExists(organizationId);
    return this.prisma.$transaction(async (tx) => {
      if (dto.isPrimary) await tx.contact.updateMany({ where: { organizationId }, data: { isPrimary: false } });
      return tx.contact.create({ data: { ...dto, email: dto.email || null, organizationId } });
    });
  }

  async updateContact(id: string, dto: UpdateContactDto) {
    const current = await this.prisma.contact.findUnique({ where: { id } });
    if (!current) throw new NotFoundException('联系人不存在');
    return this.prisma.$transaction(async (tx) => {
      if (dto.isPrimary) await tx.contact.updateMany({ where: { organizationId: current.organizationId, id: { not: id } }, data: { isPrimary: false } });
      return tx.contact.update({ where: { id }, data: { ...dto, email: dto.email || undefined } });
    });
  }

  async removeContact(id: string) { await this.requireRecord('contact', id); await this.prisma.contact.delete({ where: { id } }); return { success: true }; }
  async addDevice(organizationId: string, dto: CreateDeviceDto) { await this.ensureExists(organizationId); return this.prisma.device.create({ data: { ...dto, organizationId } }); }
  async updateDevice(id: string, dto: UpdateDeviceDto) { await this.requireRecord('device', id); return this.prisma.device.update({ where: { id }, data: dto }); }
  async removeDevice(id: string) { await this.requireRecord('device', id); await this.prisma.device.delete({ where: { id } }); return { success: true }; }
  async addProject(organizationId: string, dto: CreateProjectDto) { await this.ensureExists(organizationId); return this.prisma.project.create({ data: { ...dto, organizationId } }); }
  async updateProject(id: string, dto: UpdateProjectDto) { await this.requireRecord('project', id); return this.prisma.project.update({ where: { id }, data: dto }); }
  async removeProject(id: string) { await this.requireRecord('project', id); await this.prisma.project.delete({ where: { id } }); return { success: true }; }

  private clean<T extends CreateCustomerDto | UpdateCustomerDto>(dto: T) {
    return { ...dto, technicalOwnerId: dto.technicalOwnerId || null, businessOwnerId: dto.businessOwnerId || null };
  }

  private async ensureExists(id: string) {
    if (!await this.prisma.customerOrganization.findUnique({ where: { id }, select: { id: true } })) throw new NotFoundException('客户不存在');
  }

  private async requireRecord(type: 'contact' | 'device' | 'project', id: string) {
    const value = type === 'contact'
      ? await this.prisma.contact.findUnique({ where: { id }, select: { id: true } })
      : type === 'device'
        ? await this.prisma.device.findUnique({ where: { id }, select: { id: true } })
        : await this.prisma.project.findUnique({ where: { id }, select: { id: true } });
    if (!value) throw new NotFoundException('记录不存在');
  }
}
