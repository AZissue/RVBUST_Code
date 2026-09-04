import { CanActivate, ExecutionContext, Injectable, UnauthorizedException } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import type { Request } from 'express';
import { createHash } from 'node:crypto';
import { PrismaService } from '../prisma/prisma.service.js';
import { IS_PUBLIC_KEY } from './public.decorator.js';

@Injectable()
export class AuthGuard implements CanActivate {
  constructor(private readonly reflector: Reflector, private readonly prisma: PrismaService) {}

  async canActivate(context: ExecutionContext) {
    if (this.reflector.getAllAndOverride<boolean>(IS_PUBLIC_KEY, [context.getHandler(), context.getClass()])) return true;
    const request = context.switchToHttp().getRequest<Request>();
    const token = request.cookies?.crm_session as string | undefined;
    if (!token) throw new UnauthorizedException('请先登录');
    const tokenHash = createHash('sha256').update(token).digest('hex');
    const session = await this.prisma.authSession.findUnique({
      where: { tokenHash },
      include: { user: { include: { role: { include: { permissions: { include: { permission: true } } } } } } },
    });
    if (!session || session.expiresAt <= new Date() || !session.user.isActive) {
      if (session) await this.prisma.authSession.delete({ where: { id: session.id } }).catch(() => undefined);
      throw new UnauthorizedException('登录已失效');
    }
    request.sessionTokenHash = tokenHash;
    request.user = {
      id: session.user.id,
      username: session.user.username,
      name: session.user.name,
      email: session.user.email,
      role: session.user.role.name,
      customerOrganizationId: session.user.customerOrganizationId,
      permissions: session.user.role.permissions.map((item) => item.permission.code),
    };
    return true;
  }
}

