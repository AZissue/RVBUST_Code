import { Controller, Get, Query } from '@nestjs/common';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { DashboardService } from './dashboard.service.js';

@Controller('dashboard')
export class DashboardController {
  constructor(private readonly dashboard: DashboardService) {}
  @Get() summary(@CurrentUser() user: AuthUser) { return this.dashboard.summary(user); }
  @Get('reports') reports(@CurrentUser() user: AuthUser) { return this.dashboard.reports(user); }
  @Get('my-tickets') myTickets(@CurrentUser() user: AuthUser, @Query('from') from?: string, @Query('to') to?: string) { return this.dashboard.myTickets(user, from, to); }
  @Get('linkage-todos') linkageTodos(@CurrentUser() user: AuthUser) { return this.dashboard.linkageTodos(user); }
}
