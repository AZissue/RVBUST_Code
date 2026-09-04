import { PartialType } from '@nestjs/mapped-types';
import { IsOptional, IsString, Length } from 'class-validator';

export class CreateDeviceDto {
  @IsString() @Length(1, 120) name!: string;
  @IsOptional() @IsString() @Length(0, 120) product?: string;
  @IsOptional() @IsString() @Length(0, 100) cameraModel?: string;
  @IsOptional() @IsString() @Length(0, 120) serialNumber?: string;
  @IsOptional() @IsString() @Length(0, 80) sdkVersion?: string;
  @IsOptional() @IsString() @Length(0, 80) firmware?: string;
  @IsOptional() @IsString() @Length(0, 200) location?: string;
  @IsOptional() @IsString() @Length(0, 4000) notes?: string;
}

export class UpdateDeviceDto extends PartialType(CreateDeviceDto) {}

