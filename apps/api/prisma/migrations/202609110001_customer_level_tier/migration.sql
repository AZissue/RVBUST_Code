-- AlterEnum
ALTER TYPE "CustomerLevel" ADD VALUE 'S';

-- AlterTable
ALTER TABLE "customer_organizations" ADD COLUMN "level_locked" BOOLEAN NOT NULL DEFAULT false;
