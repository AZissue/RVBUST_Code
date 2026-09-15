import { Body, Controller, Get, Param, Patch, Post, Query, Res } from '@nestjs/common';
import type { RepairStatus } from '@prisma/client';
import type { Response } from 'express';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { AssignRepairDto, CreateRepairDto, TransitionRepairDto, UpdateRepairDto } from './dto/repair.dto.js';
import { RepairsExcelService } from './repairs-excel.service.js';
import { RepairsService } from './repairs.service.js';

@Roles('admin', 'support', 'employee')
@Controller('repairs')
export class RepairsController {
  constructor(private readonly repairs: RepairsService, private readonly excel: RepairsExcelService) {}

  @Get() list(@CurrentUser() user: AuthUser, @Query('status') status?: RepairStatus, @Query('organizationId') organizationId?: string, @Query('assigneeId') assigneeId?: string, @Query('mine') mine?: string, @Query('active') active?: string) {
    return this.repairs.list(user, { status, organizationId, assigneeId, mine: mine === '1', active: active === '1' });
  }

  @Get('export') async export(@Res() response: Response) {
    const buffer = await this.excel.buildExportBuffer();
    response.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    response.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent('维修记录导出.xlsx')}`);
    return response.send(buffer);
  }
  @Get(':id') get(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.repairs.get(user, id); }
  @Post(':id/pdf') exportPdf(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.repairs.exportPdf(user, id); }
  @Roles('admin', 'support') @Post() create(@CurrentUser() user: AuthUser, @Body() dto: CreateRepairDto) { return this.repairs.create(user, dto); }
  @Roles('admin', 'support') @Patch(':id') update(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateRepairDto) { return this.repairs.update(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/transition') transition(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: TransitionRepairDto) { return this.repairs.transition(user, id, dto); }
  @Roles('admin', 'support') @Post(':id/assign') assign(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: AssignRepairDto) { return this.repairs.assign(user, id, dto); }
}
