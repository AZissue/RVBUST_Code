import { IsBoolean, IsEmail, IsIn, IsOptional, IsString, IsUUID, Length, Matches } from 'class-validator';

export class CreateUserDto {
  @IsString() @Length(3, 60) @Matches(/^[a-zA-Z0-9._-]+$/) username!: string;
  @IsString() @Length(2, 100) name!: string;
  @IsString() @Length(10, 128) password!: string;
  @IsIn(['admin', 'support', 'employee', 'customer']) role!: string;
  @IsOptional() @IsEmail() email?: string;
  @IsOptional() @IsString() @Length(0, 40) phone?: string;
  @IsOptional() @IsBoolean() isActive?: boolean;
  @IsOptional() @IsUUID() customerOrganizationId?: string;
}

