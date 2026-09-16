import { Controller, Get } from '@nestjs/common';
import { LinkageConfigService } from './linkage-config.service.js';

/** 联动配置（任何内部登录用户可读；阈值/开关仍由 admin 在系统设置维护） */
@Controller('system')
export class LinkageConfigController {
  constructor(private readonly config: LinkageConfigService) {}

  @Get('linkage-config')
  async getLinkageConfig() {
    const defaultCreate = await this.config.getDefaultCreate();
    return { defaultCreate };
  }
}
