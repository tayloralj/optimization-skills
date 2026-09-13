---
name: linux-ebpf-io-network
description: Explain JVM latency that happens outside Java code using eBPF (BCC, bpftrace) and kernel statistics - off-CPU and run-queue latency, syscall latency, storage I/O (fsync, page cache writeback, mmap journals, major faults, O_DIRECT), and network paths (socket buffers, drops, retransmits, interrupt coalescing, RSS/RPS, busy polling, UDP and Aeron-style transports). Use when threads are waiting rather than computing, when tail latency coincides with disk or network activity, or when profilers show time in syscalls, parking, or unknown kernel frames.
---

# Linux eBPF, I/O, and Network for JVMs

On-CPU profilers miss waiting. Use kernel evidence to find where a thread
stopped running and why, then decide whether the fix belongs in Java code, JVM
configuration, the kernel, or the hardware path.

## Workflow

1. **Readiness**: run the `profiling-readiness` skill. eBPF tools need root or
   `CAP_BPF` plus `CAP_PERFMON` (kernel-dependent), BTF or kernel headers, and
   no lockdown policy blocking them. The agent does not escalate privileges.
2. **Start broad and cheap** (no privileges): `/proc/PID/task/*/stat`
   (voluntary/involuntary context switches, `majflt`), `/proc/pressure/{cpu,io,memory}`,
   `/proc/vmstat`, `/proc/net/snmp` and `nstat`, `ss -tmi`, `ethtool -S` (read),
   `iostat -x`. JFR socket/file/park events give the Java-side view.
3. **Pick one question and one tool** with `references/io-network.md`, then
   build a bounded command:

   ```bash
   install -d -m 700 ./bpf
   scripts/bpf-capture.sh --dry-run --pid "$PID" offcputime 30 ./bpf/offcpu.folded
   ```

   `--dry-run` prints the exact command for the operator to run as root. PID-
   scoped tools (offcputime, profile, runqlat, runqslower, cpudist, syscount,
   fileslower) refuse system-wide mode; system tools (biolatency, hardirqs,
   softirqs, tcpretrans) refuse a PID. Duration is capped at 600 s.
4. **Make Java stacks readable** before stack tools: `jcmd PID Compiler.perfmap`
   for JIT symbols (the script checks for the map in the target's namespace)
   and `-XX:+PreserveFramePointer` on the target JVM for complete user stacks.
   Without both, report Java frames as unresolved rather than guessing.
5. **Interpret** with workload context: separate expected waiting (idle
   consumers, park in wait strategies) from harmful waiting on the hot path.
   Correlate timestamps with the application latency timeline.
6. **Change one factor** (code path, JVM option, kernel knob via the
   `linux-low-latency-tuning` skill, NIC setting via the operator) and
   re-measure with the same capture and load.

## Low-latency specifics

- A busy-spinning consumer should show near-zero off-CPU time and run-queue
  latency on its CPU; anything else is interference.
- Journals: `fsync`/`fdatasync` and `FileChannel.force` latency, writeback
  storms (`vm.dirty_*`), and major faults on mapped files dominate tails.
  Pre-allocate and pre-fault files; keep the hot writer away from `fsync`.
- UDP media drivers (Aeron-style): receive-buffer errors (`RcvbufErrors` in
  `/proc/net/snmp`), `net.core.rmem_max`/`wmem_max` below configured socket
  buffers, NIC ring overflows (`ethtool -S`), and IRQ placement relative to
  the receiver thread.

## Guardrails

- Never run system-wide tracing or high-frequency probes on production without
  approval; kprobes on hot kernel paths add overhead to every process.
- Treat stack output, file names, and connection tuples as sensitive.
- Do not change NIC, sysctl, or I/O scheduler settings from this skill; hand an
  operator plan with rollback (lab-host runtime knobs go through the
  `linux-low-latency-tuning` skill's lab mode).
- Tool names and flags differ between BCC packages and releases; the wrapper
  resolves `*-bpfcc` and `/usr/share/bcc/tools/*`, and `--help` is the source of truth.
