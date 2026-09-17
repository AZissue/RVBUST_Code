-- CreateTable
CREATE TABLE "ticket_continuations" (
    "id" UUID NOT NULL,
    "from_ticket_id" UUID NOT NULL,
    "to_ticket_id" UUID NOT NULL,
    "note" VARCHAR(500) NOT NULL,
    "carry_links" BOOLEAN NOT NULL DEFAULT false,
    "created_by_id" UUID,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ticket_continuations_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "ticket_continuations_from_ticket_id_key" ON "ticket_continuations"("from_ticket_id");

-- CreateIndex
CREATE INDEX "ticket_continuations_to_ticket_id_idx" ON "ticket_continuations"("to_ticket_id");

-- AddForeignKey
ALTER TABLE "ticket_continuations" ADD CONSTRAINT "ticket_continuations_from_ticket_id_fkey" FOREIGN KEY ("from_ticket_id") REFERENCES "tickets"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ticket_continuations" ADD CONSTRAINT "ticket_continuations_to_ticket_id_fkey" FOREIGN KEY ("to_ticket_id") REFERENCES "tickets"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ticket_continuations" ADD CONSTRAINT "ticket_continuations_created_by_id_fkey" FOREIGN KEY ("created_by_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;
