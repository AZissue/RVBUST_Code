import { Body, Controller, Delete, Get, Param, ParseUUIDPipe, Patch, Post, Query, Res } from '@nestjs/common';
import type { LoanStatus } from '@prisma/client';
import type { Response } from 'express';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { AddFollowUpDto, AdvanceLoanDto, AssignLoanDto, CreateLoanDto, ReturnLoanDto, ScoreLoanDto, ShipLoanDto, UpdateLoanDto } from './dto/loan.dto.js';
import { LoansService } from './loans.service.js';

@Roles('admin', 'support', 'employee')
@Controller('loans')
export class LoansController {
  constructor(private readonly loans: LoansService) {}

  @Get() list(@CurrentUser() user: AuthUser, @Query('status') status?: LoanStatus, @Query('organizationId') organizationId?: string, @Query('assigneeId') assigneeId?: string, @Query('mine') mine?: string) {
    return this.loans.list(user, { status, organizationId, assigneeId, mine: mine === '1' });
  }

  @Get('list') listPage(@CurrentUser() user: AuthUser, @Query() query: Record<string, string>) {
    return this.loans.listPage(user, query);
  }

  @Get('dashboard') dashboard(@CurrentUser() user: AuthUser) {
    return this.loans.dashboard(user);
  }

  @Get('export') async export(@CurrentUser() user: AuthUser, @Query() query: Record<string, string>, @Res() response: Response) {
    const buffer = await this.loans.buildExport(user, query);
    response.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    response.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent('借测记录导出.xlsx')}`);
    return response.send(buffer);
  }
  @Get('score-rule') getScoreRule() { return this.loans.getScoreRule(); }
  @Roles('admin', 'support') @Get('recycle-bin') recycleBin(@CurrentUser() user: AuthUser) { return this.loans.listDeleted(user); }
  @Get(':id') get(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string) { return this.loans.get(user, id); }
  @Roles('admin', 'support') @Post() create(@CurrentUser() user: AuthUser, @Body() dto: CreateLoanDto) { return this.loans.create(user, dto); }
  @Roles('admin', 'support') @Patch(':id') update(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string, @Body() dto: UpdateLoanDto) { return this.loans.update(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/ship') ship(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string, @Body() dto: ShipLoanDto) { return this.loans.ship(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/advance') advance(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string, @Body() dto: AdvanceLoanDto) { return this.loans.advance(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/score') score(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string, @Body() dto: ScoreLoanDto) { return this.loans.score(user, id, dto); }
  @Post(':id/follow-ups') addFollowUp(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string, @Body() dto: AddFollowUpDto) { return this.loans.addFollowUp(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/assign') assign(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string, @Body() dto: AssignLoanDto) { return this.loans.assign(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/return') returnItems(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string, @Body() dto: ReturnLoanDto) { return this.loans.returnItems(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/cancel') cancel(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string) { return this.loans.cancel(user, id); }
  @Roles('admin', 'support') @Delete(':id') remove(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string) { return this.loans.softDelete(user, id); }
  @Roles('admin', 'support') @Post(':id/restore') restore(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string) { return this.loans.restore(user, id); }
  @Roles('admin') @Delete(':id/purge') purge(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string) { return this.loans.purge(user, id); }
}
