import { PartialType } from '@nestjs/mapped-types';
import { IsIn, IsOptional, IsString, IsUUID, Length } from 'class-validator';

export class CreateCustomerDto {
  @IsString() @Length(2, 200) name!: string;
  @IsOptional() @IsString() @Length(0, 100) region?: string;
  @IsOptional() @IsString() @Length(0, 100) industry?: string;
  @IsOptional() @IsIn(['A', 'B', 'C', 'D']) level?: string;
  @IsOptional() @IsString() @Length(0, 4000) notes?: string;
  @IsOptional() @IsUUID() technicalOwnerId?: string;
  @IsOptional() @IsUUID() businessOwnerId?: string;
}

export class UpdateCustomerDto extends PartialType(CreateCustomerDto) {}

