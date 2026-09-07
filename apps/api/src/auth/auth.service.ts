import { HttpException, HttpStatus, Injectable, UnauthorizedException } from '@nestjs/common';
import { compare, hash } from 'bcryptjs';
import { createHash, randomBytes } from 'node:crypto';
import { NotificationsService } from '../notifications/notifications.service.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { LoginDto } from './dto/login.dto.js';
import { RegisterDto } from './dto/register.dto.js';

@Injectable()
export class AuthService {
  private readonly windowMinutes = 15;
  private readonly maxAttempts = 5;

  constructor(private readonly prisma: PrismaService, private readonly notifications: NotificationsService) {}

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
    const passwordOk = Boolean(user && await compare(dto.password, user.passwordHash));
    const valid = passwordOk && user?.status === 'ACTIVE';
    await this.prisma.loginAttempt.create({ data: { username, ipAddress, success: valid } });
    if (!valid || !user) {
      await this.writeAudit(user?.id ?? null, 'auth.login_failed', ipAddress, userAgent, { username });
      if (passwordOk && user?.status === 'PENDING') throw new UnauthorizedException('账号等待管理员审批');
      if (passwordOk && user?.status === 'DISABLED') throw new UnauthorizedException('账号已被禁用');
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

  private readonly registerMessage = '注册申请已提交，请等待管理员审批';

  async register(dto: RegisterDto, ipAddress: string, userAgent?: string) {
    const username = dto.username.toLowerCase();
    const attemptKey = `register:${username}`;
    const since = new Date(Date.now() - this.windowMinutes * 60_000);
    const failures = await this.prisma.loginAttempt.count({ where: { username: attemptKey, ipAddress, success: false, createdAt: { gte: since } } });
    if (failures >= this.maxAttempts) {
      await this.writeAudit(null, 'REGISTER', ipAddress, userAgent, { username, success: false, reason: 'rate_limited' });
      throw new HttpException('注册尝试过多，请 15 分钟后再试', HttpStatus.TOO_MANY_REQUESTS);
    }
    const role = await this.prisma.role.findUnique({ where: { name: 'employee' } });
    if (!role) throw new HttpException('系统未初始化员工角色', HttpStatus.INTERNAL_SERVER_ERROR);
    let userId: string;
    try {
      const user = await this.prisma.user.create({
        data: {
          username, name: dto.name, passwordHash: await hash(dto.password, 12),
          roleId: role.id, status: 'PENDING', department: dto.department || null, phone: dto.phone || null,
        },
      });
      userId = user.id;
    } catch (error) {
      if ((error as { code?: string }).code === 'P2002') {
        // 防用户名枚举：重复注册返回与成功一致的模糊提示
        await this.prisma.loginAttempt.create({ data: { username: attemptKey, ipAddress, success: false } });
        await this.writeAudit(null, 'REGISTER', ipAddress, userAgent, { username, success: false, reason: 'duplicate' });
        return { success: true, message: this.registerMessage };
      }
      throw error;
    }
    await this.prisma.loginAttempt.create({ data: { username: attemptKey, ipAddress, success: true } });
    await this.writeAudit(userId, 'REGISTER', ipAddress, userAgent, { username, success: true });
    const admins = await this.prisma.user.findMany({ where: { status: 'ACTIVE', role: { name: 'admin' } }, select: { id: true } });
    await Promise.all(admins.map((admin) => this.notifications.notify({
      recipientId: admin.id, type: 'USER_REGISTRATION', title: '新用户注册待审批',
      body: `用户 ${dto.name}（${username}）提交了注册申请，请在用户管理中审批。`,
      dedupeKey: `user-reg:${userId}`,
    })));
    return { success: true, message: this.registerMessage };
  }

  async logout(tokenHash: string | undefined, userId: string, ipAddress: string, userAgent?: string) {
    if (tokenHash) await this.prisma.authSession.deleteMany({ where: { tokenHash, userId } });
    await this.writeAudit(userId, 'auth.logout', ipAddress, userAgent);
  }

  private async writeAudit(actorId: string | null, action: string, ipAddress: string, userAgent?: string, metadata?: object) {
    await this.prisma.auditLog.create({ data: { actorId, action, ipAddress, userAgent, metadata } });
  }
}

