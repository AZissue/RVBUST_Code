import { PartialType } from '@nestjs/mapped-types';
import { IsBoolean, IsEmail, IsOptional, IsString, Length } from 'class-validator';

export class CreateContactDto {
  @IsString() @Length(1, 100) name!: string;
  @IsOptional() @IsString() @Length(0, 100) title?: string;
  @IsOptional() @IsString() @Length(0, 40) phone?: string;
  @IsOptional() @IsEmail() email?: string;
  @IsOptional() @IsString() @Length(0, 100) wechat?: string;
  @IsOptional() @IsBoolean() isPrimary?: boolean;
}

export class UpdateContactDto extends PartialType(CreateContactDto) {}

