import { HttpException, HttpStatus, Injectable, UnauthorizedException } from '@nestjs/common';
import { compare } from 'bcryptjs';
import { createHash, randomBytes } from 'node:crypto';
import { PrismaService } from '../prisma/prisma.service.js';
import { LoginDto } from './dto/login.dto.js';

@Injectable()
export class AuthService {
  private readonly windowMinutes = 15;
  private readonly maxAttempts = 5;

  constructor(private readonly prisma: PrismaService) {}

  async login(dto: LoginDto, ipAddress: string, userAgent?: string) {
    const username = dto.username.toLowerCase();
    const since = new Date(Date.now() - this.windowMinutes * 60_000);
    const failures = await this.prisma.loginAttempt.count({ where: { username, ipAddress, success: false, createdAt: { gte: since } } });
    if (failures >= this.maxAttempts) {
      await this.writeAudit(null, 'auth.login_rate_limited', ipAddress, userAgent, { username });
      throw new HttpException('登录尝试过多，请 15 分钟后再试', HttpStatus.TOO_MANY_REQUESTS);
    }
    const user = await this.prisma.user.findUnique({
      where: { username },
      include: { role: { include: { permissions: { include: { permission: true } } } } },
    });
    const valid = Boolean(user?.isActive && await compare(dto.password, user.passwordHash));
    await this.prisma.loginAttempt.create({ data: { username, ipAddress, success: valid } });
    if (!valid || !user) {
      await this.writeAudit(user?.id ?? null, 'auth.login_failed', ipAddress, userAgent, { username });
      throw new UnauthorizedException('用户名或密码错误');
    }
    const token = randomBytes(32).toString('base64url');
    const tokenHash = createHash('sha256').update(token).digest('hex');
    const ttlHours = Math.max(1, Number(process.env.SESSION_TTL_HOURS ?? 12));
    await this.prisma.$transaction([
      this.prisma.authSession.create({ data: { tokenHash, userId: user.id, expiresAt: new Date(Date.now() + ttlHours * 3_600_000) } }),
      this.prisma.loginAttempt.deleteMany({ where: { username, ipAddress, success: false } }),
    ]);
    await this.writeAudit(user.id, 'auth.login_success', ipAddress, userAgent);
    return {
      token,
      ttlHours,
      user: {
        id: user.id, username: user.username, name: user.name, email: user.email,
        role: user.role.name, customerOrganizationId: user.customerOrganizationId,
        permissions: user.role.permissions.map((item) => item.permission.code),
      },
    };
  }

  async logout(tokenHash: string | undefined, userId: string, ipAddress: string, userAgent?: string) {
    if (tokenHash) await this.prisma.authSession.deleteMany({ where: { tokenHash, userId } });
    await this.writeAudit(userId, 'auth.logout', ipAddress, userAgent);
  }

  private async writeAudit(actorId: string | null, action: string, ipAddress: string, userAgent?: string, metadata?: object) {
    await this.prisma.auditLog.create({ data: { actorId, action, ipAddress, userAgent, metadata } });
  }
}

