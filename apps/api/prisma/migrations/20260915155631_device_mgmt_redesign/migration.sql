-- CreateEnum
CREATE TYPE "DeviceSource" AS ENUM ('MANUAL', 'REPAIR');

-- CreateEnum
CREATE TYPE "FollowUpSource" AS ENUM ('WEB', 'IMPORT', 'SYSTEM');

-- AlterEnum
ALTER TYPE "LoanStatus" ADD VALUE 'QUEUED';

-- DropIndex
DROP INDEX "devices_organization_id_serial_number_key";

-- AlterTable
ALTER TABLE "devices" ADD COLUMN     "source" "DeviceSource" NOT NULL DEFAULT 'MANUAL';

-- AlterTable
ALTER TABLE "loan_items" ADD COLUMN     "accessories" VARCHAR(200);

-- AlterTable
ALTER TABLE "loan_orders" ADD COLUMN     "advance_reason" VARCHAR(500),
ADD COLUMN     "advanced_at" TIMESTAMP(3),
ADD COLUMN     "advanced_by_id" UUID,
ADD COLUMN     "assessment_result" VARCHAR(2000),
ADD COLUMN     "deleted_at" TIMESTAMP(3),
ADD COLUMN     "info_complete" BOOLEAN NOT NULL DEFAULT false,
ADD COLUMN     "outbound_carrier" VARCHAR(50),
ADD COLUMN     "outbound_tracking" VARCHAR(100),
ADD COLUMN     "return_carrier" VARCHAR(50),
ADD COLUMN     "return_tracking" VARCHAR(100),
ADD COLUMN     "score" INTEGER,
ADD COLUMN     "score_detail" JSONB,
ADD COLUMN     "score_rule_version" VARCHAR(40),
ADD COLUMN     "ticket_id" UUID,
ALTER COLUMN "loaned_at" DROP NOT NULL,
ALTER COLUMN "due_at" DROP NOT NULL;

-- AlterTable
ALTER TABLE "repair_orders" ADD COLUMN     "deleted_at" TIMESTAMP(3),
ADD COLUMN     "inbound_carrier" VARCHAR(50),
ADD COLUMN     "inbound_tracking" VARCHAR(100),
ADD COLUMN     "outbound_carrier" VARCHAR(50),
ADD COLUMN     "parts_returned" VARCHAR(500),
ADD COLUMN     "ticket_id" UUID;

-- CreateTable
CREATE TABLE "follow_ups" (
    "id" UUID NOT NULL,
    "loan_order_id" UUID,
    "repair_order_id" UUID,
    "ticket_id" UUID,
    "author_id" UUID NOT NULL,
    "occurred_at" TIMESTAMP(3) NOT NULL,
    "content" VARCHAR(2000) NOT NULL,
    "source" "FollowUpSource" NOT NULL DEFAULT 'WEB',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "follow_ups_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "loan_score_rules" (
    "id" UUID NOT NULL,
    "version" VARCHAR(40) NOT NULL,
    "dimensions" JSONB NOT NULL,
    "is_active" BOOLEAN NOT NULL DEFAULT false,
    "description" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "loan_score_rules_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "follow_ups_loan_order_id_idx" ON "follow_ups"("loan_order_id");

-- CreateIndex
CREATE INDEX "follow_ups_repair_order_id_idx" ON "follow_ups"("repair_order_id");

-- CreateIndex
CREATE INDEX "follow_ups_ticket_id_idx" ON "follow_ups"("ticket_id");

-- CreateIndex
CREATE UNIQUE INDEX "loan_score_rules_version_key" ON "loan_score_rules"("version");

-- CreateIndex
CREATE UNIQUE INDEX "devices_serial_number_key" ON "devices"("serial_number");

-- CreateIndex
CREATE INDEX "loan_orders_ticket_id_idx" ON "loan_orders"("ticket_id");

-- CreateIndex
CREATE INDEX "loan_orders_deleted_at_idx" ON "loan_orders"("deleted_at");

-- CreateIndex
CREATE INDEX "repair_orders_deleted_at_idx" ON "repair_orders"("deleted_at");

-- AddForeignKey
ALTER TABLE "loan_orders" ADD CONSTRAINT "loan_orders_ticket_id_fkey" FOREIGN KEY ("ticket_id") REFERENCES "tickets"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "loan_orders" ADD CONSTRAINT "loan_orders_advanced_by_id_fkey" FOREIGN KEY ("advanced_by_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "repair_orders" ADD CONSTRAINT "repair_orders_ticket_id_fkey" FOREIGN KEY ("ticket_id") REFERENCES "tickets"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "follow_ups" ADD CONSTRAINT "follow_ups_loan_order_id_fkey" FOREIGN KEY ("loan_order_id") REFERENCES "loan_orders"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "follow_ups" ADD CONSTRAINT "follow_ups_repair_order_id_fkey" FOREIGN KEY ("repair_order_id") REFERENCES "repair_orders"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "follow_ups" ADD CONSTRAINT "follow_ups_ticket_id_fkey" FOREIGN KEY ("ticket_id") REFERENCES "tickets"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "follow_ups" ADD CONSTRAINT "follow_ups_author_id_fkey" FOREIGN KEY ("author_id") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
