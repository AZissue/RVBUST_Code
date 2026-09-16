import { BadRequestException, Injectable } from '@nestjs/common';
import { LoanStatus, RepairStatus, TicketEventType, Visibility } from '@prisma/client';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import type { AuthUser } from '../auth/auth.types.js';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';
import { LoansService } from '../loans/loans.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { RepairsService } from '../repairs/repairs.service.js';
import { LinkageNotifyService } from './linkage-notify.service.js';

// 进行中的单据状态集合（与迁移里的部分唯一索引一致）：同工单仅允许一张进行中同类单据
const ACTIVE_LOAN_STATUSES: LoanStatus[] = [LoanStatus.QUEUED, LoanStatus.ONGOING, LoanStatus.OVERDUE];
const ACTIVE_REPAIR_STATUSES: RepairStatus[] = [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING, RepairStatus.SHIPPED];

const isP2002 = (error: unknown) => (error as { code?: string }).code === 'P2002';

@Injectable()
export class LinkageService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly loans: LoansService,
    private readonly repairs: RepairsService,
    private readonly access: AccessPolicyService,
    private readonly linkageNotify: LinkageNotifyService,
  ) {}

  /** 从工单创建借测单（幂等）：已有进行中借测单直接返回，不重复创建 */
  async createLoanFromTicket(user: AuthUser, ticketId: string) {
    const ticket = await this.access.requireTicket(user, ticketId);
    const existing = await this.prisma.loanOrder.findFirst({ where: { ticketId, status: { in: ACTIVE_LOAN_STATUSES }, deletedAt: null }, orderBy: { createdAt: 'desc' } });
    if (existing) return { loan: existing, created: false };
    let loan: { id: string; loanNo: string; status: LoanStatus };
    try {
      loan = (await this.loans.create(user, {
        organizationId: ticket.organizationId,
        contactId: ticket.contactId ?? undefined,
        ticketId,
        purpose: ticket.description.slice(0, 200),
      }))!;
    } catch (error) {
      // 并发兜底：唯一索引冲突时返回已存在的进行中借测单
      if (!isP2002(error)) throw error;
      loan = await this.prisma.loanOrder.findFirstOrThrow({ where: { ticketId, status: { in: ACTIVE_LOAN_STATUSES }, deletedAt: null }, orderBy: { createdAt: 'desc' } });
      return { loan, created: false };
    }
    await this.prisma.ticketEvent.create({
      data: {
        ticketId, authorId: user.id, type: TicketEventType.LINK_CREATED, visibility: Visibility.INTERNAL,
        content: `已创建借测单 ${loan.loanNo}（排队中），待完善借测信息`,
        metadata: { linkType: 'loan', linkId: loan.id, linkNo: loan.loanNo },
      },
    });
    // 通知工单负责人（无负责人退化为创建人）与所有 admin，完善借测信息并评分
    const ownerId = ticket.assigneeId ?? ticket.createdById;
    const recipients = [...new Set([ownerId, ...(await this.linkageNotify.adminIds())])].filter((id): id is string => Boolean(id));
    await Promise.all(recipients.map((recipientId) => this.linkageNotify.safeNotifyUnreadOnce({
      recipientId, ticketId, type: NOTIFICATION_TYPES.LINK_LOAN_CREATED,
      title: '借测单已入队', body: `借测单 ${loan.loanNo} 已入队，请完善借测信息并评分（/loans/${loan.id}）。`,
      dedupeKey: `link-loan-created:${loan.id}`,
    })));
    return { loan, created: true };
  }

  /** 维修联动前置：为工单确保可用设备档案。返回 deviceId；有序列号时返回 null（走 repairs.create 的 SN 通道）；无任何线索时返回 null */
  private async ensureRepairDevice(ticket: {
    id: string;
    organizationId: string;
    deviceId: string | null;
    serialNumber: string | null;
    cameraModel: string | null;
  }): Promise<string | null> {
    if (ticket.deviceId) return ticket.deviceId;
    const serialNumber = ticket.serialNumber?.trim();
    if (serialNumber) {
      // SN 线索直接交给 repairs.create 的内建逻辑（按 SN 匹配或自动建档），此处不重复实现
      return null; // null 表示"走 repairs.create 的 SN 通道"
    }
    const cameraModel = ticket.cameraModel?.trim();
    if (cameraModel) {
      // 无设备无 SN 但有型号：建一条手动档案占位（状态保持默认，repairs.create 会自己置为维修中）
      const device = await this.prisma.device.create({
        data: {
          name: cameraModel,
          cameraModel,
          ownerType: 'CUSTOMER',
          source: 'MANUAL',
          organizationId: ticket.organizationId,
          notes: '由工单联动创建维修单自动建档（无序列号，待补充）',
        },
      });
      return device.id;
    }
    return null;
  }

  /** 联动失败留痕：工单事件 + 通知，避免失败信息只存在于创建接口的响应里 */
  private async recordLinkFailure(
    user: AuthUser,
    ticket: { id: string; number: string; assigneeId: string | null; createdById: string },
    linkType: 'loan' | 'repair',
    reason: string,
  ) {
    const label = linkType === 'loan' ? '借测单' : '维修单';
    await this.prisma.ticketEvent.create({
      data: {
        ticketId: ticket.id,
        authorId: user.id,
        type: TicketEventType.INTERNAL_NOTE,
        visibility: Visibility.INTERNAL,
        content: `联动创建${label}失败：${reason}`,
        metadata: { linkType, linkStatus: 'FAILED' },
      },
    });
    // 通知工单负责人（无负责人退化为创建人）与所有 admin
    const ownerId = ticket.assigneeId ?? ticket.createdById;
    const recipients = [...new Set([ownerId, ...(await this.linkageNotify.adminIds())])].filter((id): id is string => Boolean(id));
    await Promise.all(recipients.map((recipientId) => this.linkageNotify.safeNotifyUnreadOnce({
      recipientId,
      ticketId: ticket.id,
      type: NOTIFICATION_TYPES.LINK_FAILED,
      title: '联动创建失败',
      body: `工单 ${ticket.number} 联动创建${label}失败：${reason}`,
      dedupeKey: `link-failed:${ticket.id}:${linkType}`,
    })));
  }

  /** 从工单创建维修单（幂等）：已有进行中维修单直接返回，不重复创建 */
  async createRepairFromTicket(user: AuthUser, ticketId: string) {
    const ticket = await this.access.requireTicket(user, ticketId);
    const existing = await this.prisma.repairOrder.findFirst({ where: { ticketId, status: { in: ACTIVE_REPAIR_STATUSES }, deletedAt: null }, orderBy: { createdAt: 'desc' } });
    if (existing) return { repair: existing, created: false };
    let repair: { id: string; repairNo: string; status: RepairStatus };
    try {
      const deviceId = await this.ensureRepairDevice(ticket);
      if (!deviceId && !ticket.serialNumber?.trim()) {
        const reason = '工单未绑定设备，且没有序列号或相机型号，无法自动创建维修单';
        await this.recordLinkFailure(user, ticket, 'repair', reason);
        throw new BadRequestException(`${reason}；请先在工单上补充设备信息，或使用工单详情页的"创建维修单"手动入口`);
      }
      repair = (await this.repairs.create(user, {
        organizationId: ticket.organizationId,
        contactId: ticket.contactId ?? undefined,
        deviceId: deviceId ?? undefined,
        serialNumber: ticket.serialNumber ?? undefined,
        ticketId,
        symptom: ticket.description,
        receivedAt: new Date().toISOString(),
      }))!;
    } catch (error) {
      if (!isP2002(error)) throw error;
      repair = await this.prisma.repairOrder.findFirstOrThrow({ where: { ticketId, status: { in: ACTIVE_REPAIR_STATUSES }, deletedAt: null }, orderBy: { createdAt: 'desc' } });
      return { repair, created: false };
    }
    await this.prisma.ticketEvent.create({
      data: {
        ticketId, authorId: user.id, type: TicketEventType.LINK_CREATED, visibility: Visibility.INTERNAL,
        content: `已创建维修单 ${repair.repairNo}（已受理）`,
        metadata: { linkType: 'repair', linkId: repair.id, linkNo: repair.repairNo },
      },
    });
    // 维修详情为抽屉组件，链接到 /repairs 列表并带单号标识；通知所有 admin 受理
    const admins = await this.linkageNotify.adminIds();
    await Promise.all(admins.map((recipientId) => this.linkageNotify.safeNotifyUnreadOnce({
      recipientId, ticketId, type: NOTIFICATION_TYPES.LINK_REPAIR_CREATED,
      title: '新维修单待受理', body: `新维修单 ${repair.repairNo} 待受理，请前往 /repairs 处理（单号 ${repair.repairNo}）。`,
      dedupeKey: `link-repair-created:${repair.id}`,
    })));
    return { repair, created: true };
  }

  /** 工单已关联的借测单/维修单列表（创建时间倒序），供联动卡片展示 */
  async listLinks(user: AuthUser, ticketId: string) {
    await this.access.requireTicket(user, ticketId);
    const [loans, repairs] = await Promise.all([
      this.prisma.loanOrder.findMany({
        where: { ticketId, deletedAt: null },
        select: { id: true, loanNo: true, status: true, infoComplete: true, createdAt: true, assignee: { select: { id: true, name: true } } },
        orderBy: { createdAt: 'desc' },
      }),
      this.prisma.repairOrder.findMany({
        where: { ticketId, deletedAt: null },
        select: { id: true, repairNo: true, status: true, createdAt: true, assignee: { select: { id: true, name: true } } },
        orderBy: { createdAt: 'desc' },
      }),
    ]);
    return { loans, repairs };
  }
}
