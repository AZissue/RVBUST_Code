import { Body, Controller, Delete, Get, Param, ParseUUIDPipe, Patch, Post, Query } from '@nestjs/common';
import type { DeviceOwnerType, DeviceStatus } from '@prisma/client';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { DevicesService } from './devices.service.js';
import { ChangeDeviceStatusDto, CreateDeviceDto, UpdateDeviceDto } from './dto/device.dto.js';

@Roles('admin', 'support', 'employee')
@Controller('devices')
export class DevicesController {
  constructor(private readonly devices: DevicesService) {}

  @Get() list(@Query('status') status?: DeviceStatus, @Query('ownerType') ownerType?: DeviceOwnerType, @Query('organizationId') organizationId?: string, @Query('model') model?: string, @Query('keyword') keyword?: string) {
    return this.devices.list({ status, ownerType, organizationId, model, keyword });
  }

  @Roles('admin', 'support') @Get('recycle-bin') recycleBin() { return this.devices.listDeleted(); }
  @Get(':id') get(@Param('id', ParseUUIDPipe) id: string) { return this.devices.get(id); }
  @Get(':id/detail') detail(@Param('id', ParseUUIDPipe) id: string) { return this.devices.detail(id); }
  @Roles('admin', 'support') @Post() create(@Body() dto: CreateDeviceDto) { return this.devices.create(dto); }
  @Roles('admin', 'support') @Patch(':id') update(@Param('id', ParseUUIDPipe) id: string, @Body() dto: UpdateDeviceDto) { return this.devices.update(id, dto); }
  @Roles('admin', 'support') @Patch(':id/status') changeStatus(@Param('id', ParseUUIDPipe) id: string, @Body() dto: ChangeDeviceStatusDto) { return this.devices.changeStatus(id, dto); }
  @Roles('admin', 'support') @Delete(':id') remove(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string) { return this.devices.softDelete(user, id); }
  @Roles('admin', 'support') @Post(':id/restore') restore(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string) { return this.devices.restore(user, id); }
  @Roles('admin') @Delete(':id/purge') purge(@CurrentUser() user: AuthUser, @Param('id', ParseUUIDPipe) id: string) { return this.devices.purge(user, id); }
}
