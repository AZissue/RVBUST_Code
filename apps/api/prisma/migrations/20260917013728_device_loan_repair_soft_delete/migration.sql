-- AlterTable
ALTER TABLE "devices" ADD COLUMN     "deleted_at" TIMESTAMP(3),
ADD COLUMN     "deleted_by_id" UUID;

-- AlterTable
ALTER TABLE "loan_orders" ADD COLUMN     "deleted_by_id" UUID;

-- AlterTable
ALTER TABLE "repair_orders" ADD COLUMN     "deleted_by_id" UUID;

-- CreateIndex
CREATE INDEX "devices_deleted_at_idx" ON "devices"("deleted_at");

-- AddForeignKey
ALTER TABLE "devices" ADD CONSTRAINT "devices_deleted_by_id_fkey" FOREIGN KEY ("deleted_by_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "loan_orders" ADD CONSTRAINT "loan_orders_deleted_by_id_fkey" FOREIGN KEY ("deleted_by_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "repair_orders" ADD CONSTRAINT "repair_orders_deleted_by_id_fkey" FOREIGN KEY ("deleted_by_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;
