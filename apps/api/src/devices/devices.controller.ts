import { Body, Controller, Delete, Get, Param, Patch, Post, Query } from '@nestjs/common';
import type { DeviceStatus } from '@prisma/client';
import { Roles } from '../auth/roles.decorator.js';
import { DevicesService } from './devices.service.js';
import { ChangeDeviceStatusDto, CreateDeviceDto, UpdateDeviceDto } from './dto/device.dto.js';

@Roles('admin', 'support', 'employee')
@Controller('devices')
export class DevicesController {
  constructor(private readonly devices: DevicesService) {}

  @Get() list(@Query('status') status?: DeviceStatus, @Query('organizationId') organizationId?: string, @Query('model') model?: string, @Query('keyword') keyword?: string) {
    return this.devices.list({ status, organizationId, model, keyword });
  }

  @Get(':id') get(@Param('id') id: string) { return this.devices.get(id); }
  @Roles('admin', 'support') @Post() create(@Body() dto: CreateDeviceDto) { return this.devices.create(dto); }
  @Roles('admin', 'support') @Patch(':id') update(@Param('id') id: string, @Body() dto: UpdateDeviceDto) { return this.devices.update(id, dto); }
  @Roles('admin', 'support') @Patch(':id/status') changeStatus(@Param('id') id: string, @Body() dto: ChangeDeviceStatusDto) { return this.devices.changeStatus(id, dto); }
  @Roles('admin') @Delete(':id') remove(@Param('id') id: string) { return this.devices.remove(id); }
}
