# Scheduler and off-CPU correlation

Use `scripts/runqueue-delta.py --pid PID --duration 10` for an unprivileged
two-snapshot measurement of `/proc/PID/task/TID/schedstat`. It reports per-thread
on-CPU time, run-queue wait time, and timeslice deltas, and refuses a target exit
or PID reuse. Preserve the JSON beside the latency and profiler evidence.

```bash
python3 skills/linux-ebpf-io-network/scripts/runqueue-delta.py \
  --pid "$JAVA_PID" --duration 10 > "$evidence/runqueue.json"
```

The aggregate is thread-nanoseconds over the interval; it can exceed wall time
when several threads run or wait concurrently. Correlate hot TIDs with JFR,
profiler stacks, and thread names. A high run-queue delta indicates runnable
competition, quota pressure, or CPU placement interference. It does not identify
the cause by itself. `offcputime` shows blocked/off-CPU stacks, while `runqlat`
shows wake-to-run delay; use those eBPF tools only after their exact help,
permissions, and target scope are verified.

For containers, run inside the target PID namespace or use a namespace-sharing
observer. Host-wide scheduler output cannot be attributed to a pod without
matching cgroup and namespace identity. Do not change CPU quotas, scheduling
policy, IRQ routing, or capabilities from this workflow.
