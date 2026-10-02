CREATE TABLE "resiliant_dlq_events" (
	"id" bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY (sequence name "resiliant_dlq_events_id_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1),
	"event_id" text NOT NULL,
	"event_type" text NOT NULL,
	"handler_name" text NOT NULL,
	"source_destination" text,
	"source_service" text,
	"payload" jsonb NOT NULL,
	"headers" jsonb,
	"status" text DEFAULT 'pending' NOT NULL,
	"retry_count" integer DEFAULT 0 NOT NULL,
	"max_retries" integer DEFAULT 3 NOT NULL,
	"original_error" text NOT NULL,
	"last_error" text,
	"correlation_id" text,
	"user_id" text,
	"tenant_id" text,
	"failed_at" timestamp with time zone NOT NULL,
	"processed_at" timestamp with time zone,
	"next_attempt_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "resiliant_dlq_events_status_chk" CHECK ("resiliant_dlq_events"."status" in ('pending', 'approved', 'cancelled', 'processing', 'resolved', 'abandoned')),
	CONSTRAINT "resiliant_dlq_events_retry_chk" CHECK ("resiliant_dlq_events"."retry_count" >= 0 and "resiliant_dlq_events"."max_retries" >= 1)
);
--> statement-breakpoint
CREATE TABLE "resiliant_dlq_events_archive" (
	"id" bigint PRIMARY KEY NOT NULL,
	"event_id" text NOT NULL,
	"event_type" text NOT NULL,
	"handler_name" text NOT NULL,
	"source_destination" text,
	"source_service" text,
	"payload" jsonb NOT NULL,
	"headers" jsonb,
	"status" text DEFAULT 'pending' NOT NULL,
	"retry_count" integer DEFAULT 0 NOT NULL,
	"max_retries" integer DEFAULT 3 NOT NULL,
	"original_error" text NOT NULL,
	"last_error" text,
	"correlation_id" text,
	"user_id" text,
	"tenant_id" text,
	"failed_at" timestamp with time zone NOT NULL,
	"processed_at" timestamp with time zone,
	"next_attempt_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"archived_at" timestamp with time zone DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "resiliant_outbox_messages" (
	"id" bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY (sequence name "resiliant_outbox_messages_id_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1),
	"event_type" text NOT NULL,
	"target" text DEFAULT 'messaging' NOT NULL,
	"channel" text,
	"ordering_key" text,
	"payload" jsonb NOT NULL,
	"headers" jsonb,
	"status" text DEFAULT 'pending' NOT NULL,
	"retry_count" integer DEFAULT 0 NOT NULL,
	"max_retries" integer DEFAULT 10 NOT NULL,
	"last_error" text,
	"next_attempt_at" timestamp with time zone,
	"correlation_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"processed_at" timestamp with time zone,
	"event_id" text NOT NULL,
	"user_id" text,
	"source_service" text,
	CONSTRAINT "resiliant_outbox_messages_event_id_uq" UNIQUE("event_id"),
	CONSTRAINT "resiliant_outbox_messages_status_chk" CHECK ("resiliant_outbox_messages"."status" in ('pending', 'published', 'failed', 'dead_letter')),
	CONSTRAINT "resiliant_outbox_messages_retry_chk" CHECK ("resiliant_outbox_messages"."retry_count" >= 0 and "resiliant_outbox_messages"."max_retries" >= 1),
	CONSTRAINT "resiliant_outbox_messages_target_chk" CHECK (length("resiliant_outbox_messages"."target") > 0),
	CONSTRAINT "resiliant_outbox_messages_payload_chk" CHECK (jsonb_typeof("resiliant_outbox_messages"."payload") = 'object')
);
--> statement-breakpoint
CREATE TABLE "resiliant_outbox_transactions" (
	"id" bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY (sequence name "resiliant_outbox_transactions_id_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1),
	"event_type" text NOT NULL,
	"target" text DEFAULT 'messaging' NOT NULL,
	"channel" text,
	"ordering_key" text,
	"payload" jsonb NOT NULL,
	"headers" jsonb,
	"status" text DEFAULT 'pending' NOT NULL,
	"retry_count" integer DEFAULT 0 NOT NULL,
	"max_retries" integer DEFAULT 10 NOT NULL,
	"last_error" text,
	"next_attempt_at" timestamp with time zone,
	"correlation_id" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	"processed_at" timestamp with time zone,
	"request_id" text NOT NULL,
	"account_ref" text,
	"source_system" text,
	CONSTRAINT "resiliant_outbox_transactions_request_id_uq" UNIQUE("request_id"),
	CONSTRAINT "resiliant_outbox_transactions_status_chk" CHECK ("resiliant_outbox_transactions"."status" in ('pending', 'published', 'failed', 'dead_letter')),
	CONSTRAINT "resiliant_outbox_transactions_retry_chk" CHECK ("resiliant_outbox_transactions"."retry_count" >= 0 and "resiliant_outbox_transactions"."max_retries" >= 1),
	CONSTRAINT "resiliant_outbox_transactions_target_chk" CHECK (length("resiliant_outbox_transactions"."target") > 0),
	CONSTRAINT "resiliant_outbox_transactions_payload_chk" CHECK (jsonb_typeof("resiliant_outbox_transactions"."payload") = 'object')
);
--> statement-breakpoint
CREATE TABLE "resiliant_processed_events" (
	"id" bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY (sequence name "resiliant_processed_events_id_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1),
	"idempotency_key" text NOT NULL,
	"event_id" text NOT NULL,
	"event_type" text DEFAULT '' NOT NULL,
	"handler_name" text NOT NULL,
	"saga_id" text,
	"correlation_id" text,
	"tenant_id" text,
	"metadata" jsonb,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "resiliant_processed_events_key_uq" UNIQUE("idempotency_key"),
	CONSTRAINT "resiliant_processed_events_key_len_chk" CHECK (length("resiliant_processed_events"."idempotency_key") <= 512)
);
--> statement-breakpoint
CREATE TABLE "resiliant_saga_state" (
	"id" bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY (sequence name "resiliant_saga_state_id_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1),
	"saga_id" text NOT NULL,
	"name" text NOT NULL,
	"saga_key" text,
	"status" text NOT NULL,
	"current_step" text,
	"context" jsonb NOT NULL,
	"steps" jsonb NOT NULL,
	"last_error" text,
	"created_at" timestamp with time zone NOT NULL,
	"updated_at" timestamp with time zone NOT NULL,
	CONSTRAINT "resiliant_saga_state_saga_id_uq" UNIQUE("saga_id"),
	CONSTRAINT "resiliant_saga_state_status_chk" CHECK ("resiliant_saga_state"."status" in ('running', 'completed', 'compensating', 'aborted', 'failed'))
);
--> statement-breakpoint
CREATE TABLE "resiliant_scheduled_jobs" (
	"id" bigint PRIMARY KEY GENERATED ALWAYS AS IDENTITY (sequence name "resiliant_scheduled_jobs_id_seq" INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START WITH 1 CACHE 1),
	"job_name" text NOT NULL,
	"unique_key" text,
	"kind" text NOT NULL,
	"cron_expr" text,
	"interval_seconds" integer,
	"channel" text,
	"event_type" text,
	"ordering_key" text,
	"payload" jsonb NOT NULL,
	"headers" jsonb,
	"next_run_at" timestamp with time zone NOT NULL,
	"last_run_at" timestamp with time zone,
	"claimed_at" timestamp with time zone,
	"status" text DEFAULT 'scheduled' NOT NULL,
	"run_count" integer DEFAULT 0 NOT NULL,
	"max_runs" integer,
	"attempts" integer DEFAULT 0 NOT NULL,
	"max_retries" integer DEFAULT 3 NOT NULL,
	"last_error" text,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "resiliant_scheduled_jobs_status_chk" CHECK ("resiliant_scheduled_jobs"."status" in ('scheduled', 'running', 'done', 'failed', 'cancelled')),
	CONSTRAINT "resiliant_scheduled_jobs_kind_chk" CHECK ("resiliant_scheduled_jobs"."kind" in ('once', 'interval', 'cron')),
	CONSTRAINT "resiliant_scheduled_jobs_recurrence_chk" CHECK (("resiliant_scheduled_jobs"."kind" = 'cron') = ("resiliant_scheduled_jobs"."cron_expr" is not null) and ("resiliant_scheduled_jobs"."kind" = 'interval') = ("resiliant_scheduled_jobs"."interval_seconds" is not null) and ("resiliant_scheduled_jobs"."interval_seconds" is null or "resiliant_scheduled_jobs"."interval_seconds" > 0)),
	CONSTRAINT "resiliant_scheduled_jobs_counts_chk" CHECK ("resiliant_scheduled_jobs"."run_count" >= 0 and "resiliant_scheduled_jobs"."attempts" >= 0 and "resiliant_scheduled_jobs"."max_retries" >= 1)
);
--> statement-breakpoint
CREATE INDEX "resiliant_dlq_events_due_idx" ON "resiliant_dlq_events" USING btree ("id") WHERE "resiliant_dlq_events"."status" in ('pending', 'approved');--> statement-breakpoint
CREATE INDEX "resiliant_dlq_events_handler_idx" ON "resiliant_dlq_events" USING btree ("handler_name","status");--> statement-breakpoint
CREATE INDEX "resiliant_dlq_events_event_id_idx" ON "resiliant_dlq_events" USING btree ("event_id");--> statement-breakpoint
CREATE INDEX "resiliant_dlq_events_status_updated_idx" ON "resiliant_dlq_events" USING btree ("status","updated_at");--> statement-breakpoint
CREATE INDEX "resiliant_dlq_events_correlation_idx" ON "resiliant_dlq_events" USING btree ("correlation_id") WHERE "resiliant_dlq_events"."correlation_id" is not null;--> statement-breakpoint
CREATE INDEX "resiliant_dlq_events_archive_archived_idx" ON "resiliant_dlq_events_archive" USING btree ("archived_at");--> statement-breakpoint
CREATE INDEX "resiliant_dlq_events_archive_handler_idx" ON "resiliant_dlq_events_archive" USING btree ("handler_name");--> statement-breakpoint
CREATE INDEX "resiliant_dlq_events_archive_event_id_idx" ON "resiliant_dlq_events_archive" USING btree ("event_id");--> statement-breakpoint
CREATE INDEX "resiliant_outbox_messages_due_idx" ON "resiliant_outbox_messages" USING btree ("id") WHERE "resiliant_outbox_messages"."status" in ('pending', 'failed');--> statement-breakpoint
CREATE INDEX "resiliant_outbox_messages_failed_key_idx" ON "resiliant_outbox_messages" USING btree ("ordering_key","id") WHERE "resiliant_outbox_messages"."status" = 'failed';--> statement-breakpoint
CREATE INDEX "resiliant_outbox_messages_published_idx" ON "resiliant_outbox_messages" USING btree ("processed_at") WHERE "resiliant_outbox_messages"."status" = 'published';--> statement-breakpoint
CREATE INDEX "resiliant_outbox_messages_dead_idx" ON "resiliant_outbox_messages" USING btree ("id") WHERE "resiliant_outbox_messages"."status" = 'dead_letter';--> statement-breakpoint
CREATE INDEX "resiliant_outbox_messages_correlation_idx" ON "resiliant_outbox_messages" USING btree ("correlation_id") WHERE "resiliant_outbox_messages"."correlation_id" is not null;--> statement-breakpoint
CREATE INDEX "resiliant_outbox_transactions_due_idx" ON "resiliant_outbox_transactions" USING btree ("id") WHERE "resiliant_outbox_transactions"."status" in ('pending', 'failed');--> statement-breakpoint
CREATE INDEX "resiliant_outbox_transactions_failed_key_idx" ON "resiliant_outbox_transactions" USING btree ("ordering_key","id") WHERE "resiliant_outbox_transactions"."status" = 'failed';--> statement-breakpoint
CREATE INDEX "resiliant_outbox_transactions_published_idx" ON "resiliant_outbox_transactions" USING btree ("processed_at") WHERE "resiliant_outbox_transactions"."status" = 'published';--> statement-breakpoint
CREATE INDEX "resiliant_outbox_transactions_dead_idx" ON "resiliant_outbox_transactions" USING btree ("id") WHERE "resiliant_outbox_transactions"."status" = 'dead_letter';--> statement-breakpoint
CREATE INDEX "resiliant_outbox_transactions_correlation_idx" ON "resiliant_outbox_transactions" USING btree ("correlation_id") WHERE "resiliant_outbox_transactions"."correlation_id" is not null;--> statement-breakpoint
CREATE INDEX "resiliant_processed_events_event_id_idx" ON "resiliant_processed_events" USING btree ("event_id");--> statement-breakpoint
CREATE INDEX "resiliant_processed_events_created_idx" ON "resiliant_processed_events" USING btree ("created_at");--> statement-breakpoint
CREATE INDEX "resiliant_processed_events_tenant_idx" ON "resiliant_processed_events" USING btree ("tenant_id") WHERE "resiliant_processed_events"."tenant_id" is not null;--> statement-breakpoint
CREATE UNIQUE INDEX "resiliant_saga_state_name_key_uq" ON "resiliant_saga_state" USING btree ("name","saga_key") WHERE "resiliant_saga_state"."saga_key" is not null;--> statement-breakpoint
CREATE INDEX "resiliant_saga_state_status_idx" ON "resiliant_saga_state" USING btree ("status","name");--> statement-breakpoint
CREATE INDEX "resiliant_scheduled_jobs_due_idx" ON "resiliant_scheduled_jobs" USING btree ("next_run_at") WHERE "resiliant_scheduled_jobs"."status" = 'scheduled';--> statement-breakpoint
CREATE INDEX "resiliant_scheduled_jobs_running_idx" ON "resiliant_scheduled_jobs" USING btree ("claimed_at") WHERE "resiliant_scheduled_jobs"."status" = 'running';--> statement-breakpoint
CREATE INDEX "resiliant_scheduled_jobs_job_name_idx" ON "resiliant_scheduled_jobs" USING btree ("job_name","status");--> statement-breakpoint
CREATE UNIQUE INDEX "resiliant_scheduled_jobs_unique_key_uq" ON "resiliant_scheduled_jobs" USING btree ("unique_key") WHERE "resiliant_scheduled_jobs"."unique_key" is not null and "resiliant_scheduled_jobs"."status" in ('scheduled', 'running');