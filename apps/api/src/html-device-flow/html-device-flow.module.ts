import { Module } from '@nestjs/common';
import { HtmlDeviceFlowController } from './html-device-flow.controller.js';
import { HtmlDeviceFlowService } from './html-device-flow.service.js';

@Module({ controllers: [HtmlDeviceFlowController], providers: [HtmlDeviceFlowService] })
export class HtmlDeviceFlowModule {}
