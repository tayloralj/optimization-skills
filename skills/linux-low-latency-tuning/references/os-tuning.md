# Low-latency OS tuning reference

Kernel parameter behaviour depends on version and configuration. Check
`Documentation/admin-guide/kernel-parameters.txt` for the running kernel and
verify every change with measurement.

## Interference sources and remedies

| Source | Evidence | Remedy (runtime / boot) | Cost / risk |
| --- | --- | --- | --- |
| CFS quota throttling | cgroup `cpu.stat` `nr_throttled`, `throttled_usec` | Remove `cpu.max` quota; use cpusets | Capacity planning moves to cores |
| Other tasks on hot CPUs | `perf sched timehist -C`, runqlat, `/proc/PID/task/*/stat` migrations | cpuset partition or `isolcpus=domain,managed_irq,<cpus>`; pin everything else away | Unpinned work cannot use those CPUs |
| Device IRQs on hot CPUs | `/proc/interrupts` deltas; audit `irqs_on_hot_cpus` | `/proc/irq/N/smp_affinity_list` to housekeeping; `irqaffinity=` boot; ban CPUs in irqbalance | Some managed IRQs cannot move without `managed_irq` |
| Scheduler tick | `LOC` rate on hot CPUs | `nohz_full=<cpus>` (needs `CONFIG_NO_HZ_FULL`, one runnable task per CPU) | Tick moves to housekeeping; accounting cost |
| RCU callbacks | `rcuc`/`rcuog` kthreads, softirq `RCU` counts | `rcu_nocbs=<cpus>` (often implied by `nohz_full`) | Callbacks run on housekeeping CPUs |
| Unbound workqueues, kthreads | `ps -eLo psr,comm` on hot CPUs | `/sys/devices/virtual/workqueue/cpumask`; kthread affinity | Some per-CPU kthreads are unavoidable |
| Timer migration | Timers firing on idle hot CPUs | `kernel.timer_migration=0` | Negligible |
| vmstat updates | `vmstat_update` work on hot CPUs | `vm.stat_interval` larger | Stale stats |
| Softlockup / NMI watchdog | Periodic interrupts | `watchdog_cpumask` to housekeeping; `nmi_watchdog=0` | Lose lockup detection on those CPUs |
| Frequency transitions | Latency variance, `cpupower monitor` | `performance` governor / EPP; boost policy fixed | Power and thermal |
| Deep idle exits | cpuidle `usage`/`time` on hot CPUs; state `latency` | Disable deep states per CPU; PM QoS (`/dev/cpu_dma_latency` held open); `processor.max_cstate`/`intel_idle.max_cstate`; `idle=poll` (extreme) | Power; shared-core turbo headroom |
| SMT sibling activity | Sibling CPU busy while hot thread runs | Reserve both siblings, or `smt/control=off` for the experiment | Halves logical CPUs |
| THP compaction / khugepaged | Latency spikes with `compact_stall`, `thp_collapse_alloc` in `/proc/vmstat` | THP `madvise` + defrag `madvise`/`defer`; JVM `-XX:+UseTransparentHugePages`, or hugetlbfs + `-XX:+UseLargePages` | Explicit hugepages must be reserved |
| Page faults on hot path | `majflt`/`minflt` per thread | `-XX:+AlwaysPreTouch`, pre-fault mapped files, no swap | Startup time, RSS |
| Swap | `pswpin/pswpout` | Disable swap on latency hosts or `swappiness` low; size memory | OOM instead of stall |
| Automatic NUMA balancing | `numa_hint_faults` in `/proc/vmstat` | `kernel.numa_balancing=0` with explicit placement | Manual placement burden |
| KSM | `ksmd` CPU, COW faults | `ksm/run=0` | Memory dedupe lost |
| Clocksource not TSC | `current_clocksource` | Fix TSC stability (BIOS, `tsc=reliable` only with evidence) | Wrong time if TSC is unstable |

## Isolation approaches

1. **cgroup v2 cpuset partitions** (runtime, recent kernels): a partition
   with `cpuset.cpus.partition=isolated` removes CPUs from load balancing
   without a reboot. Check kernel documentation for availability.
2. **Boot-time `isolcpus`**: long-standing and widely used for trading hosts;
   described as deprecated in favour of cpusets in kernel docs but still
   supported. Combine with `nohz_full`, `rcu_nocbs`, `irqaffinity`.
3. **tuned `cpu-partitioning` / `latency-performance` / `network-latency`**:
   packaged operator-managed profiles (RHEL family and others) that bundle many
   of the above. Treat as persistent configuration with a change record.

## JVM thread placement

- Map Java threads to native TIDs: `jcmd PID Thread.print` (`nid=0x...`, hex)
  or `/proc/PID/task/TID/comm` (native thread names, truncated to 15 bytes). Name
  hot threads explicitly in code.
- Pin in-process with a maintained affinity library (for example OpenHFT
  Java-Thread-Affinity) or externally with `taskset -pc CPU TID` after the
  thread exists; re-verify after restarts and thread recreation.
- Start the JVM with a mask that includes housekeeping CPUs so GC/JIT
  ergonomics are sane; then move only hot threads onto isolated CPUs.
  Starting the whole JVM inside the isolated set shrinks GC/JIT thread counts
  and places them next to the hot path.
- Busy-spin wait strategies should call `Thread.onSpinWait()` (x86 `PAUSE`);
  its cost differs across microarchitectures, so benchmark the wait strategy
  on the deployment CPU. Back off to yield/park when idle for long periods.
- Java thread priorities have no effect on Linux by default; do not rely on
  `ThreadPriorityPolicy`. Real-time scheduling classes require root, RT
  throttling review (`sched_rt_runtime_us`), and a watchdog plan.

## NIC and network interrupts (summary)

Put NIC queue IRQs for the hot flow on a housekeeping CPU in the same cache
domain as the consumer thread, or deliberately on a dedicated core. Review
interrupt coalescing (`ethtool -c`), queue counts (`ethtool -l`), RPS/XPS, and
busy polling; details in the `linux-ebpf-io-network` skill.

## Validation toolkit

- Application: HdrHistogram from intended send time; hiccup/jitter meter
  (the `java-latency-measurement` skill ships one).
- Kernel noise: `rtla osnoise` / `rtla timerlat` (kernel tools, root),
  `cyclictest` (rt-tests), `perf sched timehist -C <cpus>`,
  `perf stat -e irq_vectors:local_timer_entry -C <cpus>`.
- Counters: `/proc/interrupts`, `/proc/softirqs`, `/proc/vmstat`
  (`compact_stall`, `thp_*`, `numa_*`), cgroup `cpu.stat`.
