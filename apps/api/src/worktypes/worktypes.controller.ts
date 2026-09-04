import { Body, Controller, Get, Param, Patch, Post, Query } from '@nestjs/common';
import { Roles } from '../auth/roles.decorator.js';
import { CreateWorkTypeDto, UpdateWorkTypeDto } from './dto/work-type.dto.js';
import { WorktypesService } from './worktypes.service.js';

@Roles('admin', 'support', 'employee')
@Controller('work-types')
export class WorktypesController {
  constructor(private readonly worktypes: WorktypesService) {}
  @Get() list(@Query('all') all?: string) { return this.worktypes.list(all !== '1'); }
  @Roles('admin') @Post() create(@Body() dto: CreateWorkTypeDto) { return this.worktypes.create(dto); }
  @Roles('admin') @Patch(':id') update(@Param('id') id: string, @Body() dto: UpdateWorkTypeDto) { return this.worktypes.update(id, dto); }
}
