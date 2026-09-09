import { Controller, Get, Query } from '@nestjs/common';
import { Roles } from '../auth/roles.decorator.js';
import { AuditService } from './audit.service.js';

@Roles('admin')
@Controller('audit-logs')
export class AuditController {
  constructor(private readonly audit: AuditService) {}
  @Get() list(@Query('page') pageRaw?: string) {
    const page = Math.max(1, Number.parseInt(pageRaw ?? '1', 10) || 1);
    return this.audit.list(page);
  }
}

