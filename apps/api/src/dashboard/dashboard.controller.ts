import { Controller, Get } from '@nestjs/common';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { DashboardService } from './dashboard.service.js';

@Controller('dashboard')
export class DashboardController {
  constructor(private readonly dashboard: DashboardService) {}
  @Get() summary(@CurrentUser() user: AuthUser) { return this.dashboard.summary(user); }
  @Get('reports') reports(@CurrentUser() user: AuthUser) { return this.dashboard.reports(user); }
}
