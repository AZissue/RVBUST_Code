ALTER TABLE "repair_orders" ADD COLUMN "return_form" JSONB;
ALTER TABLE "attachments" ADD COLUMN "loan_item_id" UUID,
  ADD COLUMN "photo_category" VARCHAR(20), ADD COLUMN "photo_slot" INTEGER,
  ADD COLUMN "photo_key" UUID;
ALTER TABLE "attachments" ADD CONSTRAINT "attachments_loan_item_id_fkey"
  FOREIGN KEY ("loan_item_id") REFERENCES "loan_items"("id") ON DELETE CASCADE;
CREATE UNIQUE INDEX "attachments_photo_key_key" ON "attachments"("photo_key");
CREATE UNIQUE INDEX "attachments_loan_item_id_photo_category_photo_slot_key"
  ON "attachments"("loan_item_id", "photo_category", "photo_slot");
ALTER TABLE "attachments" ADD CONSTRAINT "loan_photo_slot_valid" CHECK (
  ("loan_item_id" IS NULL AND "photo_category" IS NULL AND "photo_slot" IS NULL AND "photo_key" IS NULL)
  OR ("loan_item_id" IS NOT NULL AND "photo_category" IS NOT NULL AND "photo_slot" IS NOT NULL AND "photo_key" IS NOT NULL
    AND "ticket_id" IS NULL AND "repair_order_id" IS NULL
    AND (("photo_category" = 'VIEWS' AND "photo_slot" BETWEEN 1 AND 9)
      OR ("photo_category" = 'ACCESSORIES' AND "photo_slot" BETWEEN 1 AND 5)
      OR ("photo_category" = 'SERIAL' AND "photo_slot" = 1)))
);
