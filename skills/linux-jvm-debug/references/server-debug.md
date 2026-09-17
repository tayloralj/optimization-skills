# Linux server debug routing

Use existing system tools for context, then route to one JVM skill:

| Symptom | First evidence | Next skill |
| --- | --- | --- |
| high CPU | readiness, launch JFR, CPU profile | `java-flight-recorder` or `java-linux-perf` |
| latency spikes | open-loop validity, JFR, run-queue and frequency context | `java-latency-measurement` |
| GC pauses | unified GC/safepoint log and JFR | `java-gc-tuning` |
| memory/RSS growth | heap and NMT snapshots, cgroup/OOM evidence | `java-native-memory` |
| hung or blocked | thread dumps, lock owners, off-CPU evidence | `java-async-profiler` or `linux-ebpf-io-network` |
| crash/restart | `journalctl`, `coredumpctl`, `hs_err` and service status | `java-offline-capture` |

On a service managed by systemd, an operator can provide these read-only
outputs alongside the JVM capture:

```bash
systemctl show UNIT --no-pager
journalctl -u UNIT --since '15 minutes ago' --no-pager
coredumpctl info PID --no-pager
```

These commands can require service or journal permissions. The collector does
not use `sudo`, change units, restart services, or collect the whole journal.
Redact secrets, command lines, paths, and host identifiers before transfer.
