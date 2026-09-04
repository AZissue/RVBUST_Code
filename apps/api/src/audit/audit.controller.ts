import { Controller, Get } from '@nestjs/common';
import { Roles } from '../auth/roles.decorator.js';
import { AuditService } from './audit.service.js';

@Roles('admin')
@Controller('audit-logs')
export class AuditController {
  constructor(private readonly audit: AuditService) {}
  @Get() list() { return this.audit.list(); }
}

