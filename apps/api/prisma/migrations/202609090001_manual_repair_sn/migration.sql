ALTER TABLE "repair_orders" ALTER COLUMN "device_id" DROP NOT NULL;
ALTER TABLE "repair_orders" ADD COLUMN "serial_number" VARCHAR(120);
UPDATE "repair_orders" r SET "serial_number" = d."serial_number"
FROM "devices" d WHERE r."device_id" = d."id";
