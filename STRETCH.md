# Task 5 — 5,000 Worker Weekend Launch Plan

## What breaks first

1. Local audio storage.
2. Upload bandwidth and request timeouts.
3. Synchronous metadata extraction under concurrency.
4. Duplicate submissions after retries.
5. SQLite concurrent writes.
6. Missing monitoring and failure recovery.

## Before launch

- Move audio to S3-compatible object storage.
- Move production metadata to managed PostgreSQL.
- Use signed direct uploads.
- Process metadata asynchronously with a queue and worker pool.
- Add idempotency keys and file hashes.
- Enforce file size, duration and format limits.
- Add authentication and rate limiting.
- Add retries and a dead-letter state.
- Monitor errors, queue depth, storage, CPU and processing latency.
- Back up the database and define storage retention.
- Load-test thousands of concurrent uploads before launch.

## Cost

Storage and bandwidth are major variable costs, followed by metadata-processing compute. Object storage with lifecycle policies is preferable to local server disk.
