import { Body, Controller, Delete, Get, Param, Patch, Post, Put } from '@nestjs/common';
import { Roles } from '../auth/roles.decorator.js';
import { UpsertSettingDto } from './dto/setting.dto.js';
import { CreateTeamDto, UpdateTeamDto } from './dto/team.dto.js';
import { SystemService } from './system.service.js';

@Roles('admin')
@Controller('system')
export class SystemController {
  constructor(private readonly system: SystemService) {}
  @Get('roles') roles() { return this.system.roles(); }
  @Get('teams') teams() { return this.system.teams(); }
  @Post('teams') createTeam(@Body() dto: CreateTeamDto) { return this.system.createTeam(dto); }
  @Patch('teams/:id') updateTeam(@Param('id') id: string, @Body() dto: UpdateTeamDto) { return this.system.updateTeam(id, dto); }
  @Delete('teams/:id') removeTeam(@Param('id') id: string) { return this.system.removeTeam(id); }
  @Get('settings') settings() { return this.system.settings(); }
  @Put('settings') upsertSetting(@Body() dto: UpsertSettingDto) { return this.system.upsertSetting(dto); }
}

