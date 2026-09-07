import { Body, Controller, Get, Param, Patch, Post, Query } from '@nestjs/common';
import type { LoanStatus } from '@prisma/client';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { AssignLoanDto, CreateLoanDto, ReturnLoanDto, UpdateLoanDto } from './dto/loan.dto.js';
import { LoansService } from './loans.service.js';

@Roles('admin', 'support', 'employee')
@Controller('loans')
export class LoansController {
  constructor(private readonly loans: LoansService) {}

  @Get() list(@CurrentUser() user: AuthUser, @Query('status') status?: LoanStatus, @Query('organizationId') organizationId?: string, @Query('assigneeId') assigneeId?: string, @Query('mine') mine?: string) {
    return this.loans.list(user, { status, organizationId, assigneeId, mine: mine === '1' });
  }

  @Get(':id') get(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.loans.get(user, id); }
  @Roles('admin', 'support') @Post() create(@CurrentUser() user: AuthUser, @Body() dto: CreateLoanDto) { return this.loans.create(user, dto); }
  @Roles('admin', 'support') @Patch(':id') update(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateLoanDto) { return this.loans.update(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/assign') assign(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: AssignLoanDto) { return this.loans.assign(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/return') returnItems(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: ReturnLoanDto) { return this.loans.returnItems(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/cancel') cancel(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.loans.cancel(user, id); }
}
