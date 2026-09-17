-- AlterTable
ALTER TABLE "devices" ADD COLUMN "flow_id" VARCHAR(100);

-- CreateIndex
CREATE UNIQUE INDEX "devices_flow_id_key" ON "devices"("flow_id");

-- AlterTable
ALTER TABLE "follow_ups" ADD COLUMN "flow_id" VARCHAR(100);

-- CreateIndex
CREATE UNIQUE INDEX "follow_ups_flow_id_key" ON "follow_ups"("flow_id");

-- AlterTable
ALTER TABLE "loan_orders" ADD COLUMN "flow_id" VARCHAR(100);

-- CreateIndex
CREATE UNIQUE INDEX "loan_orders_flow_id_key" ON "loan_orders"("flow_id");

-- AlterTable
ALTER TABLE "repair_orders" ADD COLUMN "flow_id" VARCHAR(100);

-- CreateIndex
CREATE UNIQUE INDEX "repair_orders_flow_id_key" ON "repair_orders"("flow_id");
