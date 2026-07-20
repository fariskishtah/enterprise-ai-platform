# Redis issues

Owner: Platform

## Impact

Authentication/session cache and Dramatiq broker operations may fail or queue processing may stop.

## Symptoms

- `RedisExporterDown` or `RedisMemorySaturation` fires.
- Backend or worker logs report Redis connectivity/timeouts.

## Dashboard and queries

Platform Overview (`http://localhost:3000/d/platform-overview`)

```promql
redis_memory_used_bytes / redis_memory_max_bytes
```

## Immediate checks

1. Run `docker compose ps redis redis-exporter` and `docker compose exec redis redis-cli ping`.
2. Inspect memory, connected clients, rejected connections, and broker latency metrics.
3. Confirm whether `maxmemory` is non-zero; the saturation alert intentionally stays inactive when unlimited.

## Diagnosis

- Exporter failure is not proof Redis is down; verify PING and application connectivity.
- Memory pressure with a configured limit requires understanding keys/queues before any eviction action.

## Mitigation

- Restore connectivity or reduce the confirmed producer pressure through normal application controls.
- Do not flush Redis, delete queues, or change eviction policy without explicit authority and a recovery plan.

## Escalation

Escalate for data-loss risk, queue corruption, rejected writes, or any proposed key/volume deletion.

## Verification

1. Redis PING and exporter scrape remain healthy.
2. Broker-backed jobs progress and API Redis operations recover.
3. Memory ratio remains below 85% when a max is configured.

