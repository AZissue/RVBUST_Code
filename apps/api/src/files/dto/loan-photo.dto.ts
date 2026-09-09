import { IsIn, IsUUID } from 'class-validator';
export const PHOTO_LIMITS = { VIEWS: 9, ACCESSORIES: 5, SERIAL: 1 } as const;
export class LoanPhotoDto {
  @IsIn(Object.keys(PHOTO_LIMITS)) category!: keyof typeof PHOTO_LIMITS;
  @IsUUID() photoKey!: string;
}
