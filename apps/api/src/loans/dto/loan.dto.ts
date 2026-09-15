import { PartialType } from '@nestjs/mapped-types';
import { ArrayMaxSize, IsArray, IsBoolean, IsDateString, IsIn, IsInt, IsObject, IsOptional, IsString, IsUUID, Length, Max, Min, ValidateNested } from 'class-validator';
import { Type } from 'class-transformer';

/** 常用物流承运商（下拉选项，允许其他） */
export const LOAN_CARRIERS = ['顺丰', '京东物流', '德邦', '中通', '圆通', '申通', '韵达', '极兔', 'EMS', '邮政', '跨越速运', '安能', '其他'] as const;

export class CreateLoanDto {
  @IsUUID() organizationId!: string;
  @IsOptional() @IsUUID() contactId?: string;
  @IsOptional() @IsUUID() ticketId?: string;
  @IsString() @Length(1, 500) purpose!: string;
  @IsOptional() @IsString() @Length(0, 2000) assessmentResult?: string;
  @IsOptional() @IsInt() @Min(0) @Max(100) score?: number;
  @IsOptional() @IsObject() scoreDetail?: Record<string, number>;
  @IsOptional() @IsString() @Length(0, 100) agreementNo?: string;
  @IsOptional() @IsString() @Length(0, 4000) note?: string;
}

/** 排队中的借测单允许补录/调整基础信息；进行中单仅允许改日期与备注 */
export class UpdateLoanDto extends PartialType(CreateLoanDto) {
  @IsOptional() @IsDateString() loanedAt?: string;
  @IsOptional() @IsDateString() dueAt?: string;
}

export class ManualLoanDeviceDto {
  @IsString() @Length(1, 120) serialNumber!: string;
  @IsOptional() @IsString() @Length(0, 100) cameraModel?: string;
}

export class ShipLoanDto {
  @IsArray() @ArrayMaxSize(50) @IsUUID('4', { each: true }) deviceIds!: string[];
  @IsDateString() loanedAt!: string;
  @IsDateString() dueAt!: string;
  @IsOptional() @IsString() @Length(0, 100) agreementNo?: string;
  @IsOptional() @IsIn(LOAN_CARRIERS) outboundCarrier?: string;
  @IsOptional() @IsString() @Length(0, 100) outboundTracking?: string;
  @IsOptional() @IsArray() @ArrayMaxSize(50) @ValidateNested({ each: true }) @Type(() => ManualLoanDeviceDto) manualDevices?: ManualLoanDeviceDto[];
}

export class AdvanceLoanDto {
  @IsString() @Length(2, 500) reason!: string;
}

export class ScoreLoanDto {
  @IsOptional() @IsInt() @Min(0) @Max(100) score?: number;
  @IsOptional() @IsObject() scoreDetail?: Record<string, number>;
  @IsOptional() @IsBoolean() infoComplete?: boolean;
  @IsOptional() @IsString() @Length(0, 2000) assessmentResult?: string;
}

export class AddFollowUpDto {
  @IsString() @Length(1, 2000) content!: string;
  @IsOptional() @IsDateString() occurredAt?: string;
}

export class AssignLoanDto {
  @IsUUID() assigneeId!: string;
}

export class ReturnLoanItemDto {
  @IsUUID() deviceId!: string;
  @IsOptional() @IsString() @Length(0, 2000) conditionNote?: string;
}

export class ReturnLoanDto {
  @IsOptional() @IsArray() @ValidateNested({ each: true }) @Type(() => ReturnLoanItemDto) items?: ReturnLoanItemDto[];
}
