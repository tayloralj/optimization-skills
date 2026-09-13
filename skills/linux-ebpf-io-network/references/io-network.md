# I/O and network reference

## Question → evidence

| Question | Unprivileged evidence | eBPF / privileged |
| --- | --- | --- |
| Is the thread off-CPU on the hot path? | `/proc/PID/task/TID/status` ctxt switches; JFR `jdk.ThreadPark`, `jdk.JavaMonitorEnter` | `offcputime` folded stacks; `cpudist -O` |
| Is it runnable but waiting for a CPU? | `/proc/PID/task/TID/schedstat` (2nd field = run-queue wait ns); `/proc/pressure/cpu` | `runqlat`, `runqslower` |
| Which syscalls are slow? | JFR file/socket events | `syscount -L` |
| Are file writes/fsync slow? | JFR `jdk.FileWrite`, `jdk.FileForce`; `iostat -x` | `fileslower`, `biolatency -D`, `ext4slower`/`xfsslower` |
| Page faults on mapped files? | `majflt` per task; `/proc/vmstat` `pgmajfault` | bpftrace on `exceptions:page_fault_user` (x86) |
| Packet drops / buffer overflow? | `nstat -az`, `/proc/net/snmp` (`RcvbufErrors`, `InErrors`), `ss -tmi`, `ethtool -S` | `tcpretrans`, `softirqs`, `hardirqs` |
| Interrupt placement? | `/proc/interrupts` deltas, `/proc/irq/N/effective_affinity_list` | `hardirqs -d` |

`schedstat` fields: time on CPU (ns), time waiting on a run queue (ns), number
of timeslices. Sample twice for per-thread run-queue delay without privileges.

## bpftrace one-liners (operator, root)

Validate each on the target kernel; tracepoint names and argument fields vary.

```bash
# Run-queue latency histogram, all tasks (µs), 30 s
bpftrace -e 'tracepoint:sched:sched_wakeup,tracepoint:sched:sched_wakeup_new { @q[args.pid] = nsecs; }
  tracepoint:sched:sched_switch /@q[args.next_pid]/ { @lat_us = hist((nsecs - @q[args.next_pid]) / 1000); delete(@q[args.next_pid]); }
  interval:s:30 { exit(); }'

# fsync/fdatasync latency by process name (µs), 30 s
bpftrace -e 'tracepoint:syscalls:sys_enter_fsync,tracepoint:syscalls:sys_enter_fdatasync { @s[tid] = nsecs; }
  tracepoint:syscalls:sys_exit_fsync,tracepoint:syscalls:sys_exit_fdatasync /@s[tid]/ { @us[comm] = hist((nsecs - @s[tid]) / 1000); delete(@s[tid]); }
  interval:s:30 { exit(); }'

# Major page faults by thread name, 30 s (x86 tracepoint)
bpftrace -e 'software:major-faults:1 /pid == TARGET_PID/ { @[comm] = count(); } interval:s:30 { exit(); }'
```

The first one-liner is system-wide (the wakee's TGID is not available at wakeup
time); prefer `bpf-capture.sh runqlat --pid` for a process-scoped answer.

## Storage paths for Java

- `FileChannel.write` returns after the page cache copy; durability needs
  `force(false)` (fdatasync-like) or `force(true)`. Measure `force` latency
  separately from write latency.
- `RandomAccessFile.setLength` creates sparse files; pre-allocate blocks (write
  zeros or `fallocate` via tooling) before latency-sensitive appends.
- `MappedByteBuffer` / `MemorySegment` mapped journals fault pages on first
  touch; pre-touch during startup. `force()` on a mapping flushes dirty pages
  and can stall.
- `ExtendedOpenOption.DIRECT` (JDK 10+) enables `O_DIRECT` with aligned buffers
  (`FileStore.getBlockSize`); bypasses page cache and writeback surprises at the
  cost of doing your own caching.
- Writeback: large `vm.dirty_ratio` lets dirty pages accumulate and flush in
  bursts; byte-based `vm.dirty_background_bytes` gives smoother flushing.
  Changes are host-wide and operator-owned.
- NVMe normally uses the `none` scheduler; check
  `/sys/block/DEV/queue/scheduler`. Device write cache, filesystem journal mode,
  and `noatime`/`relatime` matter for journal-heavy workloads.

## Network paths for Java

- TCP: `TCP_NODELAY` for request/response latency (Nagle plus delayed ACK can
  add tens of ms); `jdk.net.ExtendedSocketOptions` exposes `TCP_QUICKACK` and
  keepalive tuning on Linux. Socket buffer sizes are capped by
  `net.core.rmem_max`/`wmem_max` and auto-tuned by `net.ipv4.tcp_rmem`/`tcp_wmem`.
- UDP: receive buffer overflow shows as `RcvbufErrors`; the application must
  drain fast enough or the buffer must absorb bursts — both are measurable.
- NIC: interrupt coalescing (`ethtool -c`; adaptive modes trade latency for
  CPU), ring sizes (`ethtool -g`), queue count (`ethtool -l`), RSS indirection,
  RPS/XPS masks, GRO/LRO (throughput versus per-packet latency). Place queue
  IRQs deliberately relative to the consumer thread and cache domain.
- Busy polling (`net.core.busy_poll`, `busy_read`, `SO_BUSY_POLL`) reduces
  interrupt-driven wakeups at CPU cost; plain Java APIs do not set
  `SO_BUSY_POLL` per socket, so it is usually host-wide or via native code.
- Kernel-bypass stacks (vendor user-space TCP/UDP, DPDK, AF_XDP) are hardware-
  and vendor-specific experiments outside this skill's scope.
- Loopback and same-host benchmarks hide NIC, interrupt, and switch behaviour.
