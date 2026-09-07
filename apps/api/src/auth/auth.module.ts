import { Module } from '@nestjs/common';
import { NotificationsModule } from '../notifications/notifications.module.js';
import { AuthController } from './auth.controller.js';
import { AuthService } from './auth.service.js';
import { AccessPolicyService } from './access-policy.service.js';

@Module({ imports: [NotificationsModule], controllers: [AuthController], providers: [AuthService, AccessPolicyService], exports: [AuthService, AccessPolicyService] })
export class AuthModule {}
