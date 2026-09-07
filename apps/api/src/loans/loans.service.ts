import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { LoanStatus, type Prisma } from '@prisma/client';
import { randomInt } from 'node:crypto';
import type { AuthUser } from '../auth/auth.types.js';
import { NotificationsService } from '../notifications/notifications.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { AssignLoanDto, CreateLoanDto, ReturnLoanDto, UpdateLoanDto } from './dto/loan.dto.js';

const loanInclude = {
  organization: { select: { id: true, name: true } },
  contact: { select: { id: true, name: true, phone: true } },
  assignee: { select: { id: true, name: true } },
  items: { include: { device: { select: { id: true, name: true, serialNumber: true, cameraModel: true, status: true } } } },
} as const;

@Injectable()
export class LoansService {
  constructor(private readonly prisma: PrismaService, private readonly notifications: NotificationsService) {}

  private scopeWhere(user: AuthUser): Prisma.LoanOrderWhereInput {
    if (user.role === 'employee') return { OR: [{ assigneeId: user.id }, { createdById: user.id }] };
    return {};
  }

  private requireInternal(user: AuthUser) {
    if (user.role === 'customer') throw new BadRequestException('客户账号不能访问借还单');
  }

  // 惰性逾期修正：ONGOING 且 dueAt 已过的单置为 OVERDUE，并幂等通知创建人与负责人
  private async fixOverdue() {
    const now = new Date();
    const overdue = await this.prisma.loanOrder.findMany({ where: { status: LoanStatus.ONGOING, dueAt: { lt: now } }, select: { id: true, loanNo: true, createdById: true, assigneeId: true } });
    if (!overdue.length) return;
    await this.prisma.loanOrder.updateMany({ where: { id: { in: overdue.map((loan) => loan.id) }, status: LoanStatus.ONGOING, dueAt: { lt: now } }, data: { status: LoanStatus.OVERDUE } });
    await Promise.all(overdue.flatMap((loan) => [...new Set([loan.createdById, loan.assigneeId].filter(Boolean) as string[])].map((recipientId) =>
      this.notifications.notify({ recipientId, type: 'LOAN_OVERDUE', severity: 'WARNING', title: '借出单已逾期', body: `借出单 ${loan.loanNo} 已超过应还日期，请尽快跟进归还。`, dedupeKey: `loan-overdue:${loan.id}` }),
    )));
  }

  async list(user: AuthUser, query: { status?: LoanStatus; organizationId?: string; assigneeId?: string; mine?: boolean }) {
    this.requireInternal(user);
    if (query.status && !Object.values(LoanStatus).includes(query.status)) throw new BadRequestException('借出单状态无效');
    await this.fixOverdue();
    return this.prisma.loanOrder.findMany({
      where: {
        AND: [this.scopeWhere(user)],
        status: query.status,
        organizationId: query.organizationId,
        assigneeId: query.mine ? user.id : query.assigneeId,
      },
      include: loanInclude, orderBy: { updatedAt: 'desc' }, take: 500,
    });
  }

  async get(user: AuthUser, id: string) {
    this.requireInternal(user);
    await this.fixOverdue();
    const loan = await this.prisma.loanOrder.findFirst({ where: { id, AND: [this.scopeWhere(user)] }, include: loanInclude });
    if (!loan) throw new NotFoundException('借出单不存在');
    return loan;
  }

  async create(user: AuthUser, dto: CreateLoanDto) {
    return this.prisma.$transaction(async (tx) => {
      if (!await tx.customerOrganization.findUnique({ where: { id: dto.organizationId }, select: { id: true } })) throw new BadRequestException('客户组织不存在');
      if (dto.contactId && !await tx.contact.findFirst({ where: { id: dto.contactId, organizationId: dto.organizationId }, select: { id: true } })) throw new BadRequestException('联系人不属于该客户');
      const deviceIds = [...new Set(dto.deviceIds)];
      const devices = await tx.device.findMany({ where: { id: { in: deviceIds } } });
      if (devices.length !== deviceIds.length) throw new BadRequestException('设备不存在');
      for (const device of devices) {
        if (device.ownerType !== 'COMPANY') throw new BadRequestException('客户资产不能创建借测单');
        if (device.status !== 'IN_STOCK') throw new BadRequestException(`设备 ${device.name}（${device.serialNumber ?? device.id}）当前不可借出`);
      }
      const data = {
        organizationId: dto.organizationId, contactId: dto.contactId || null, createdById: user.id,
        purpose: dto.purpose, loanedAt: dto.loanedAt ? new Date(dto.loanedAt) : new Date(), dueAt: new Date(dto.dueAt),
        agreementNo: dto.agreementNo || null, note: dto.note || null,
        items: { create: deviceIds.map((deviceId) => ({ deviceId })) },
      };
      let loan;
      for (let attempt = 0; attempt < 4; attempt++) {
        try { loan = await tx.loanOrder.create({ data: { ...data, loanNo: this.generateNo() }, include: loanInclude }); break; }
        catch (error) { if ((error as { code?: string }).code !== 'P2002' || attempt === 3) throw error; }
      }
      // 公司样机临时挂靠到借测客户名下
      await tx.device.updateMany({ where: { id: { in: deviceIds } }, data: { status: 'LOANED', organizationId: dto.organizationId } });
      return loan;
    });
  }

  async update(user: AuthUser, id: string, dto: UpdateLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.ONGOING && loan.status !== LoanStatus.OVERDUE) throw new BadRequestException('仅进行中的借出单可以修改');
    if (dto.deviceIds) throw new BadRequestException('设备清单不支持修改，请取消后重新建单');
    if (dto.contactId && !await this.prisma.contact.findFirst({ where: { id: dto.contactId, organizationId: loan.organizationId }, select: { id: true } })) throw new BadRequestException('联系人不属于该客户');
    return this.prisma.loanOrder.update({
      where: { id },
      data: {
        purpose: dto.purpose, note: dto.note, agreementNo: dto.agreementNo, contactId: dto.contactId,
        loanedAt: dto.loanedAt ? new Date(dto.loanedAt) : undefined,
        dueAt: dto.dueAt ? new Date(dto.dueAt) : undefined,
      },
      include: loanInclude,
    });
  }

  async assign(user: AuthUser, id: string, dto: AssignLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status === LoanStatus.RETURNED || loan.status === LoanStatus.CANCELLED) throw new BadRequestException('已结束的借出单不能指派');
    const assignee = await this.prisma.user.findFirst({ where: { id: dto.assigneeId, status: 'ACTIVE', role: { name: { in: ['admin', 'support', 'employee'] } } } });
    if (!assignee) throw new BadRequestException('被指派者不存在或不是内部成员');
    const updated = await this.prisma.loanOrder.update({ where: { id }, data: { assigneeId: dto.assigneeId }, include: loanInclude });
    await this.notifications.notify({ recipientId: dto.assigneeId, type: 'LOAN_ASSIGNED', title: '借出单已指派给你', body: `借出单 ${loan.loanNo} 已指派给你跟进。`, dedupeKey: `loan-assign:${loan.id}:${dto.assigneeId}` });
    return updated;
  }

  async returnItems(user: AuthUser, id: string, dto: ReturnLoanDto) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.ONGOING && loan.status !== LoanStatus.OVERDUE) throw new BadRequestException('该借出单不在可归还状态');
    const notes = new Map((dto.items ?? []).map((item) => [item.deviceId, item.conditionNote]));
    return this.prisma.$transaction(async (tx) => {
      const now = new Date();
      for (const item of loan.items) {
        await tx.loanItem.update({ where: { id: item.id }, data: { returnedAt: item.returnedAt ?? now, conditionNote: notes.get(item.deviceId) ?? item.conditionNote } });
      }
      // 公司样机归还后回公司库存（解除临时挂靠）；客户资产不会出现在借测单中，防御性排除
      await tx.device.updateMany({ where: { id: { in: loan.items.map((item) => item.deviceId) }, ownerType: 'COMPANY' }, data: { status: 'IN_STOCK', organizationId: null } });
      return tx.loanOrder.update({ where: { id }, data: { status: LoanStatus.RETURNED, returnedAt: now }, include: loanInclude });
    });
  }

  async cancel(user: AuthUser, id: string) {
    const loan = await this.get(user, id);
    if (loan.status !== LoanStatus.ONGOING && loan.status !== LoanStatus.OVERDUE) throw new BadRequestException('该借出单不能取消');
    return this.prisma.$transaction(async (tx) => {
      await tx.device.updateMany({ where: { id: { in: loan.items.map((item) => item.deviceId) }, ownerType: 'COMPANY' }, data: { status: 'IN_STOCK', organizationId: null } });
      return tx.loanOrder.update({ where: { id }, data: { status: LoanStatus.CANCELLED }, include: loanInclude });
    });
  }

  private generateNo() {
    const date = new Date().toISOString().slice(2, 10).replaceAll('-', '');
    return `L-${date}${randomInt(0, 1000).toString().padStart(3, '0')}`;
  }
}
