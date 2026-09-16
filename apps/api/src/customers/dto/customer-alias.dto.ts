import { Transform } from 'class-transformer';
import { IsString, IsUUID, Length } from 'class-validator';

export class CreateCustomerAliasDto {
  @IsUUID() organizationId!: string;
  /** 纠错别名（错字词），入库前 trim，trim 后需 1-100 字 */
  @Transform(({ value }) => (typeof value === 'string' ? value.trim() : value))
  @IsString() @Length(1, 100) alias!: string;
}
