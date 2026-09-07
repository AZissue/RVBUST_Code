import { PartialType } from '@nestjs/mapped-types';
import { IsIn, IsOptional, IsString, IsUrl, IsUUID, Length, ValidateIf } from 'class-validator';

export class CreateCustomerDto {
  @IsString() @Length(2, 200) name!: string;
  @IsOptional() @IsString() @Length(0, 100) region?: string;
  @IsOptional() @IsString() @Length(0, 100) industry?: string;
  @IsOptional() @IsIn(['A', 'B', 'C', 'D']) level?: string;
  @IsOptional() @IsString() @Length(0, 4000) notes?: string;
  @IsOptional() @IsUUID() technicalOwnerId?: string;
  @IsOptional() @IsUUID() businessOwnerId?: string;
  @IsOptional() @ValidateIf((_, value) => value !== '') @IsUrl({ protocols: ['http', 'https'], require_protocol: true }) @Length(0, 500) websiteUrl?: string;
  @IsOptional() @ValidateIf((_, value) => value !== '') @IsUrl({ protocols: ['http', 'https'], require_protocol: true }) @Length(0, 500) wikiRef?: string;
  @IsOptional() @IsString() @Length(0, 5000) background?: string;
  @IsOptional() @IsString() @Length(0, 5000) applicationScenarios?: string;
  @IsOptional() @IsString() @Length(0, 5000) projectNeeds?: string;
}

export class UpdateCustomerDto extends PartialType(CreateCustomerDto) {}
