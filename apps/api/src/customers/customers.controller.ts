import { Body, Controller, Delete, Get, Param, Patch, Post, Query } from '@nestjs/common';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { CustomersService } from './customers.service.js';
import { CreateContactDto, UpdateContactDto } from './dto/contact.dto.js';
import { CreateCustomerDto, UpdateCustomerDto } from './dto/customer.dto.js';
import { CreateDeviceDto, UpdateDeviceDto } from './dto/device.dto.js';
import { CreateProjectDto, UpdateProjectDto } from './dto/project.dto.js';

@Controller()
export class CustomersController {
  constructor(private readonly customers: CustomersService) {}

  @Get('customers') list(@CurrentUser() user: AuthUser, @Query('search') search?: string) { return this.customers.list(user, search); }
  @Get('customers/:id') get(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.customers.get(user, id); }
  @Roles('admin', 'support') @Post('customers') create(@Body() dto: CreateCustomerDto) { return this.customers.create(dto); }
  @Roles('admin', 'support') @Patch('customers/:id') update(@Param('id') id: string, @Body() dto: UpdateCustomerDto) { return this.customers.update(id, dto); }
  @Roles('admin') @Delete('customers/:id') remove(@Param('id') id: string) { return this.customers.remove(id); }

  @Roles('admin', 'support') @Post('customers/:id/contacts') addContact(@Param('id') id: string, @Body() dto: CreateContactDto) { return this.customers.addContact(id, dto); }
  @Roles('admin', 'support') @Patch('contacts/:id') updateContact(@Param('id') id: string, @Body() dto: UpdateContactDto) { return this.customers.updateContact(id, dto); }
  @Roles('admin', 'support') @Delete('contacts/:id') removeContact(@Param('id') id: string) { return this.customers.removeContact(id); }

  @Roles('admin', 'support') @Post('customers/:id/devices') addDevice(@Param('id') id: string, @Body() dto: CreateDeviceDto) { return this.customers.addDevice(id, dto); }
  @Roles('admin', 'support') @Patch('devices/:id') updateDevice(@Param('id') id: string, @Body() dto: UpdateDeviceDto) { return this.customers.updateDevice(id, dto); }
  @Roles('admin', 'support') @Delete('devices/:id') removeDevice(@Param('id') id: string) { return this.customers.removeDevice(id); }
  @Get('devices') listDevices(@CurrentUser() user: AuthUser) {
    return this.customers.listDevices(user);
  }
  @Roles('admin', 'support', 'employee') @Get('projects') listProjects() { return this.customers.listProjects(); }

  @Roles('admin', 'support') @Post('customers/:id/projects') addProject(@Param('id') id: string, @Body() dto: CreateProjectDto) { return this.customers.addProject(id, dto); }
  @Roles('admin', 'support') @Patch('projects/:id') updateProject(@Param('id') id: string, @Body() dto: UpdateProjectDto) { return this.customers.updateProject(id, dto); }
  @Roles('admin', 'support') @Delete('projects/:id') removeProject(@Param('id') id: string) { return this.customers.removeProject(id); }
}
