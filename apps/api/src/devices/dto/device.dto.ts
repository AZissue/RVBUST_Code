import { PartialType } from '@nestjs/mapped-types';
import { DeviceStatus } from '@prisma/client';
import { IsDateString, IsEnum, IsOptional, IsString, IsUUID, Length } from 'class-validator';

export class CreateDeviceDto {
  @IsUUID() organizationId!: string;
  @IsString() @Length(1, 120) name!: string;
  @IsOptional() @IsString() @Length(0, 120) product?: string;
  @IsOptional() @IsString() @Length(0, 100) cameraModel?: string;
  @IsOptional() @IsString() @Length(0, 120) serialNumber?: string;
  @IsOptional() @IsString() @Length(0, 80) sdkVersion?: string;
  @IsOptional() @IsString() @Length(0, 80) firmware?: string;
  @IsOptional() @IsString() @Length(0, 200) location?: string;
  @IsOptional() @IsEnum(DeviceStatus) status?: DeviceStatus;
  @IsOptional() @IsDateString() purchaseDate?: string;
  @IsOptional() @IsDateString() warrantyUntil?: string;
  @IsOptional() @IsString() @Length(0, 4000) notes?: string;
}

export class UpdateDeviceDto extends PartialType(CreateDeviceDto) {}

export class ChangeDeviceStatusDto {
  @IsEnum(DeviceStatus) status!: DeviceStatus;
}
