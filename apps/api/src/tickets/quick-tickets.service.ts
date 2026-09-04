import { BadRequestException, ConflictException, Inject, Injectable } from '@nestjs/common';
import type { AuthUser } from '../auth/auth.types.js';
import { AccessPolicyService } from '../auth/access-policy.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { QUICK_INPUT_PARSER, type QuickInputParser, ticketSimilarity } from './quick-input.parser.js';
import { SimilarTicketsDto, UpdateQuickTicketDto } from './dto/quick-ticket.dto.js';

@Injectable()
export class QuickTicketsService {
  constructor(private readonly prisma: PrismaService, private readonly access: AccessPolicyService, @Inject(QUICK_INPUT_PARSER) private readonly parser: QuickInputParser) {}

  async parse(user: AuthUser, rawText: string) {
    this.access.requireInternal(user);
    const customers = await this.prisma.customerOrganization.findMany({ where: this.access.customerWhere(user), select: { id: true, name: true } });
    const users = await this.prisma.user.findMany({ where: { isActive: true, role: { name: { in: ['admin', 'support', 'employee'] } } }, select: { id: true, name: true, username: true } });
    const result = this.parser.parse(rawText, { customers, users, currentUserId: user.id });
    const devices = result.matchedCustomer && result.deviceText ? await this.prisma.device.findMany({ where: { organizationId: result.matchedCustomer.id, OR: [{ cameraModel: { equals: result.deviceText, mode: 'insensitive' } }, { name: { equals: result.deviceText, mode: 'insensitive' } }] }, select: { id: true, name: true, serialNumber: true, cameraModel: true } }) : [];
    const similarTickets = result.matchedCustomer && result.issue ? await this.similar(user, { organizationId: result.matchedCustomer.id, issue: result.issue, cameraModel: result.deviceText }) : [];
    return { ...result, deviceCandidates: devices, matchedDevice: devices.length === 1 ? devices[0] : null, similarTickets };
  }

  async similar(user: AuthUser, dto: SimilarTicketsDto) {
    this.access.requireInternal(user);
    await this.access.requireCustomer(user, dto.organizationId);
    const tickets = await this.prisma.ticket.findMany({ where: { AND: [this.access.ticketWhere(user), { organizationId: dto.organizationId }] }, include: { organization: { select: { id: true, name: true } }, device: true, assignee: { select: { id: true, name: true } } } });
    return tickets.map((t) => ({ ...t, similarity: Math.max(ticketSimilarity(dto.issue, t.title, dto.cameraModel ?? '', t.cameraModel ?? t.device?.cameraModel ?? '', !['CLOSED', 'RESOLVED'].includes(t.status)), ticketSimilarity(dto.issue, t.description, dto.cameraModel ?? '', t.cameraModel ?? t.device?.cameraModel ?? '', !['CLOSED', 'RESOLVED'].includes(t.status))) }))
      .filter((t) => t.similarity >= 40).sort((a, b) => b.similarity - a.similarity).slice(0, 6);
  }

  async update(user: AuthUser, id: string, dto: UpdateQuickTicketDto) {
    this.access.requireInternal(user);
    await this.access.requireTicket(user, id);
    if (!dto.issue.trim()) throw new BadRequestException('问题描述不能为空');
    if (!await this.prisma.user.findFirst({ where: { id: dto.assigneeId, isActive: true, role: { name: { in: ['admin', 'support', 'employee'] } } } })) throw new BadRequestException('负责人不可分配');
    return this.prisma.$transaction(async (tx) => {
      const result = await tx.ticket.updateMany({ where: { id, organizationId: dto.organizationId, updatedAt: new Date(dto.expectedUpdatedAt) }, data: { assigneeId: dto.assigneeId, priority: dto.priority, updatedAt: new Date() } });
      if (!result.count) throw new ConflictException('工单已变化或客户不一致，请重新检查相似工单');
      await tx.ticketEvent.create({ data: { ticketId: id, authorId: user.id, type: 'INTERNAL_NOTE', visibility: 'INTERNAL', content: dto.issue, metadata: { source: 'QUICK_INPUT', rawText: dto.rawText, assigneeId: dto.assigneeId, priority: dto.priority } } });
      return tx.ticket.findUniqueOrThrow({ where: { id } });
    });
  }
}
