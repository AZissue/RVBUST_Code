-- 借测协议附件：photo_category 增加 AGREEMENT（每单 1 份）
ALTER TABLE "attachments" DROP CONSTRAINT "loan_photo_slot_valid";
ALTER TABLE "attachments" ADD CONSTRAINT "loan_photo_slot_valid" CHECK (
  ("loan_item_id" IS NULL AND "photo_category" IS NULL AND "photo_slot" IS NULL AND "photo_key" IS NULL)
  OR ("loan_item_id" IS NOT NULL AND "photo_category" IS NOT NULL AND "photo_slot" IS NOT NULL AND "photo_key" IS NOT NULL
    AND "ticket_id" IS NULL AND "repair_order_id" IS NULL
    AND (("photo_category" = 'VIEWS' AND "photo_slot" BETWEEN 1 AND 9)
      OR ("photo_category" = 'ACCESSORIES' AND "photo_slot" BETWEEN 1 AND 5)
      OR ("photo_category" = 'SERIAL' AND "photo_slot" = 1)
      OR ("photo_category" = 'AGREEMENT' AND "photo_slot" = 1)))
);
