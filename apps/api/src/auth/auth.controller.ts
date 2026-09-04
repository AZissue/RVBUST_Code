import { Body, Controller, Get, Post, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import { AuthService } from './auth.service.js';
import type { AuthUser } from './auth.types.js';
import { CurrentUser } from './current-user.decorator.js';
import { LoginDto } from './dto/login.dto.js';
import { Public } from './public.decorator.js';

@Controller('auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Public()
  @Post('login')
  async login(@Body() dto: LoginDto, @Req() request: Request, @Res({ passthrough: true }) response: Response) {
    const result = await this.auth.login(dto, request.ip ?? 'unknown', request.get('user-agent'));
    response.cookie('crm_session', result.token, {
      httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: result.ttlHours * 3_600_000,
    });
    return { user: result.user };
  }

  @Get('me')
  me(@CurrentUser() user: AuthUser) { return { user }; }

  @Post('logout')
  async logout(@Req() request: Request, @Res({ passthrough: true }) response: Response, @CurrentUser() user: AuthUser) {
    await this.auth.logout(request.sessionTokenHash, user.id, request.ip ?? 'unknown', request.get('user-agent'));
    response.clearCookie('crm_session', { httpOnly: true, sameSite: 'lax', path: '/' });
    return { success: true };
  }
}

