import { CallHandler, ExecutionContext, Injectable, NestInterceptor } from '@nestjs/common';
import type { Request } from 'express';
import { mergeMap, Observable } from 'rxjs';
import { AuditService } from './audit.service.js';

@Injectable()
export class AuditInterceptor implements NestInterceptor {
  constructor(private readonly audit: AuditService) {}

  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const request = context.switchToHttp().getRequest<Request>();
    if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method) || request.path.startsWith('/api/auth/')) return next.handle();
    return next.handle().pipe(mergeMap(async (result) => {
      await this.audit.write({
        actorId: request.user?.id,
        action: `http.${request.method.toLowerCase()}`,
        entityType: request.path.split('/')[2] ?? 'unknown',
        entityId: Array.isArray(request.params?.id) ? request.params.id[0] : request.params?.id,
        ipAddress: request.ip,
        userAgent: request.get('user-agent'),
        metadata: { path: request.path, status: 'success' },
      });
      return result;
    }));
  }
}
