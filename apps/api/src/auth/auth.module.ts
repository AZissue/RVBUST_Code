import { Module } from '@nestjs/common';
import { AuthController } from './auth.controller.js';
import { AuthService } from './auth.service.js';
import { AccessPolicyService } from './access-policy.service.js';

@Module({ controllers: [AuthController], providers: [AuthService, AccessPolicyService], exports: [AuthService, AccessPolicyService] })
export class AuthModule {}
