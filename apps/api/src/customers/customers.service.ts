import { ConflictException, BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import type { CustomerLevel, Prisma } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { computeCustomerLevel, recentMonthKeys } from './customer-level.js';
import { CreateContactDto, UpdateContactDto } from './dto/contact.dto.js';
import { CreateCustomerAliasDto } from './dto/customer-alias.dto.js';
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

  /**
   * 客户列表。不传 page 时保持旧行为返回全部数组（快速录入等下拉场景）；
   * 传 page 时返回分页对象 { items, total, page, pageSize }，支持 level 筛选（S/A/B/C，按有效等级）。
   */
  async list(user: AuthUser, search?: string, page?: number, pageSize = 20, levelFilter?: string) {
    const customers = await this.prisma.customerOrganization.findMany({
      where: {
        ...this.access.customerWhere(user),
        ...(search ? { OR: [{ name: { contains: search, mode: 'insensitive' } }, { industry: { contains: search, mode: 'insensitive' } }] } : {}),
      },
      include: { contacts: { where: { isPrimary: true }, take: 1 }, _count: { select: { devices: true, projects: true, tickets: true } } },
      orderBy: { updatedAt: 'desc' },
    });
    const graded = await this.withLevels(customers);
    // 重点客户排前，同级按最近更新
    const rank = { S: 0, A: 1, B: 2, C: 3 } as const;
    graded.sort((a, b) => rank[a.level as keyof typeof rank] - rank[b.level as keyof typeof rank] || b.updatedAt.getTime() - a.updatedAt.getTime());
    if (page === undefined) return graded;
    const filtered = levelFilter ? graded.filter((customer) => customer.level === levelFilter) : graded;
    const start = (page - 1) * pageSize;
    return { items: filtered.slice(start, start + pageSize), total: filtered.length, page, pageSize };
  }

  /** 批量计算有效等级：覆盖 level 字段，并附 levelSource / levelLocked / monthTicketCount */
  private async withLevels<T extends { id: string; level: CustomerLevel | null; levelLocked: boolean }>(customers: T[]) {
    const keys = recentMonthKeys(new Date());
    const start = new Date(new Date().getFullYear(), new Date().getMonth() - 2, 1);
    const tickets = customers.length
      ? await this.prisma.ticket.findMany({
          where: { organizationId: { in: customers.map((customer) => customer.id) }, deletedAt: null, createdAt: { gte: start } },
          select: { organizationId: true, createdAt: true },
        })
      : [];
    const monthKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    return customers.map((customer) => {
      const monthly: [number, number, number] = [0, 0, 0];
      for (const ticket of tickets) {
        if (ticket.organizationId !== customer.id) continue;
        const index = keys.indexOf(monthKey(ticket.createdAt) as (typeof keys)[number]);
        if (index >= 0) monthly[index] += 1;
      }
      const { level, source } = computeCustomerLevel({ storedLevel: customer.level, levelLocked: customer.levelLocked, monthlyTicketCounts: monthly });
      return { ...customer, level, levelSource: source, monthTicketCount: monthly[0] };
    });
  }

  async get(user: AuthUser, id: string) {
    await this.access.requireCustomer(user, id);
    const customer = await this.prisma.customerOrganization.findUnique({ where: { id }, include: detailInclude });
    if (!customer) throw new NotFoundException('客户不存在');
    return (await this.withLevels([customer]))[0];
  }

  async profile(user: AuthUser, id: string) {
    const organization = await this.prisma.customerOrganization.findUnique({ where: { id } });
    if (!organization) throw new NotFoundException('客户不存在');
    if (user.role === 'employee' && organization.technicalOwnerId !== user.id && organization.businessOwnerId !== user.id) throw new NotFoundException('客户不存在');
    const [graded, contacts, devices, tickets, loanOrders, repairOrders] = await Promise.all([
      this.withLevels([organization]),
      this.prisma.contact.findMany({ where: { organizationId: id }, orderBy: [{ isPrimary: 'desc' }, { name: 'asc' }] }),
      this.prisma.device.findMany({ where: { organizationId: id }, orderBy: { createdAt: 'desc' } }),
      this.prisma.ticket.findMany({ where: { organizationId: id }, select: { id: true, number: true, title: true, status: true, priority: true, createdAt: true, assignee: { select: { id: true, name: true } } }, orderBy: { createdAt: 'desc' }, take: 20 }),
      this.prisma.loanOrder.findMany({ where: { organizationId: id }, include: { contact: { select: { id: true, name: true } }, assignee: { select: { id: true, name: true } }, items: { include: { device: { select: { id: true, name: true, serialNumber: true } } } } }, orderBy: { createdAt: 'desc' }, take: 50 }),
      this.prisma.repairOrder.findMany({ where: { organizationId: id }, include: { device: { select: { id: true, name: true, serialNumber: true } }, contact: { select: { id: true, name: true } }, assignee: { select: { id: true, name: true } } }, orderBy: { createdAt: 'desc' }, take: 50 }),
    ]);
    return { organization: graded[0], contacts, devices, tickets, loanOrders, repairOrders };
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
    try { const customer = await this.prisma.customerOrganization.create({ data: this.clean(dto), include: detailInclude }); return (await this.withLevels([customer]))[0]; }
    catch (error) { if ((error as { code?: string }).code === 'P2002') throw new ConflictException('客户公司名称已存在'); throw error; }
  }

  async update(id: string, dto: UpdateCustomerDto) {
    await this.ensureExists(id);
    const customer = await this.prisma.customerOrganization.update({ where: { id }, data: this.clean(dto), include: detailInclude });
    return (await this.withLevels([customer]))[0];
  }

  async remove(id: string) {
    await this.ensureExists(id);
    try { await this.prisma.customerOrganization.delete({ where: { id } }); return { success: true }; }
    catch (error) { if ((error as { code?: string }).code === 'P2003') throw new ConflictException('客户仍有关联工单或账号，不能删除'); throw error; }
  }

  /** 记录快速工单纠错别名（确认页改选触发）。幂等：同客户同别名已存在时静默成功；并发唯一冲突同样视为成功 */
  async addAlias(user: AuthUser, dto: CreateCustomerAliasDto) {
    const alias = dto.alias.trim();
    if (!alias || alias.length > 100) throw new BadRequestException('别名长度需在 1-100 字之间');
    await this.access.requireCustomer(user, dto.organizationId);
    const existing = await this.prisma.customerAlias.findUnique({ where: { organizationId_alias: { organizationId: dto.organizationId, alias } } });
    if (existing) return { ok: true };
    try { await this.prisma.customerAlias.create({ data: { organizationId: dto.organizationId, alias, createdById: user.id } }); }
    catch (error) { if ((error as { code?: string }).code !== 'P2002') throw error; }
    return { ok: true };
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
