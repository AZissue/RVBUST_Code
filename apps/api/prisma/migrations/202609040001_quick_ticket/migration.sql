ALTER TABLE "tickets" ADD COLUMN "raw_text" TEXT;
ALTER TABLE "tickets" ADD COLUMN "request_key" UUID;
CREATE UNIQUE INDEX "tickets_request_key_key" ON "tickets"("request_key");
ALTER TABLE "work_items" ADD COLUMN "converted_ticket_id" UUID;
CREATE UNIQUE INDEX "work_items_converted_ticket_id_key" ON "work_items"("converted_ticket_id");
ALTER TABLE "work_items" ADD CONSTRAINT "work_items_converted_ticket_id_fkey" FOREIGN KEY ("converted_ticket_id") REFERENCES "tickets"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
