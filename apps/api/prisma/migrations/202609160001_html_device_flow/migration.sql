CREATE TABLE "html_flow_state" (
    "id" VARCHAR(32) NOT NULL,
    "revision" INTEGER NOT NULL DEFAULT 0,
    "data" JSONB NOT NULL,
    "updated_at" TIMESTAMP(3) NOT NULL,
    CONSTRAINT "html_flow_state_pkey" PRIMARY KEY ("id")
);

CREATE TABLE "html_flow_followups" (
    "id" VARCHAR(100) NOT NULL,
    "record_id" VARCHAR(100) NOT NULL,
    "sequence" INTEGER NOT NULL,
    "person" TEXT,
    "date" VARCHAR(40),
    "content" TEXT NOT NULL,
    "source" TEXT,
    "deleted_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "html_flow_followups_pkey" PRIMARY KEY ("id")
);
CREATE INDEX "html_flow_followups_record_id_sequence_idx" ON "html_flow_followups"("record_id", "sequence");

CREATE TABLE "html_flow_files" (
    "id" UUID NOT NULL,
    "storage_key" VARCHAR(300) NOT NULL,
    "original_name" VARCHAR(255) NOT NULL,
    "mime_type" VARCHAR(120) NOT NULL,
    "size_bytes" INTEGER NOT NULL,
    "created_by_id" UUID NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "html_flow_files_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "html_flow_files_storage_key_key" ON "html_flow_files"("storage_key");
