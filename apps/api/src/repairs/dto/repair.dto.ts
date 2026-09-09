import { PartialType } from '@nestjs/mapped-types';
import { RepairStatus } from '@prisma/client';
import { IsBoolean, IsDateString, IsEnum, IsOptional, IsString, IsUUID, Length, ValidateNested, IsObject } from 'class-validator';
import { Type } from 'class-transformer';
import { ReturnFormDto } from './return-form.dto.js';

export class CreateRepairDto {
  @IsOptional() @IsBoolean() manualSerialNumber?: boolean;
  @IsOptional() @IsObject() @ValidateNested() @Type(() => ReturnFormDto) returnForm?: ReturnFormDto;
  @IsUUID() organizationId!: string;
  @IsOptional() @IsUUID() deviceId?: string;
  @IsOptional() @IsString() @Length(1, 120) serialNumber?: string;
  @IsString() @Length(1, 1000) symptom!: string;
  @IsOptional() @IsString() @Length(0, 4000) faultCause?: string;
  @IsOptional() @IsString() @Length(0, 4000) resolution?: string;
  @IsOptional() @IsBoolean() inWarranty?: boolean;
  @IsOptional() @IsUUID() contactId?: string;
  @IsOptional() @IsDateString() receivedAt?: string;
  @IsOptional() @IsString() @Length(0, 4000) note?: string;
}

export class UpdateRepairDto {
  @IsOptional() @IsObject() @ValidateNested() @Type(() => ReturnFormDto) returnForm?: ReturnFormDto;
  @IsOptional() @IsString() @Length(1, 1000) symptom?: string;
  @IsOptional() @IsString() @Length(0, 4000) faultCause?: string;
  @IsOptional() @IsString() @Length(0, 4000) resolution?: string;
  @IsOptional() @IsString() @Length(0, 100) trackingNo?: string;
  @IsOptional() @IsString() @Length(0, 4000) note?: string;
  @IsOptional() @IsBoolean() inWarranty?: boolean;
  @IsOptional() @IsUUID() contactId?: string;
}

export class TransitionRepairDto {
  @IsEnum(RepairStatus) status!: RepairStatus;
  @IsOptional() @IsString() @Length(0, 100) trackingNo?: string;
  @IsOptional() @IsString() @Length(0, 2000) content?: string;
}

export class AssignRepairDto {
  @IsUUID() assigneeId!: string;
}
