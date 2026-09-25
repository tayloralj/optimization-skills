# Native triage: bounded captures and symptom routing

Commands checked against perf 7.0, gdb 17.1, GNU binutils 2.46, and glibc on
Ubuntu (x86-64). Confirm options with the target host's `--help` output. Run
captures as the target's user unless the host policy says otherwise.

## Bounded baseline captures

Replace `MODE` with `fp` or `dwarf` from the `cpp-build-readiness` report.

```bash
# Counters for 10 s, no stacks: cycles, instructions, context switches, faults
perf stat -p "$PID" -- sleep 10

# On-CPU stacks for 30 s at 99 Hz
perf record -F 99 --call-graph MODE -p "$PID" -o cpu.perf.data -- sleep 30
perf report -i cpu.perf.data --no-children --sort dso,sym

# Syscall counts and time per thread for 10 s (futex time suggests lock waits)
perf trace -s -p "$PID" -- sleep 10
```

`perf trace` reads syscall tracepoints and fails with "No permissions to read
/sys/kernel/tracing" where tracefs is root-only, which is common; treat that
as blocked, not as "no syscalls". `perf stat` counts that show
`<not counted>` or a percentage in brackets were not counted, or were
multiplexed; do not compare them as exact.

`--call-graph dwarf` copies 8192 bytes of user stack per sample by default,
so keep duration and frequency low. With LTO or heavy inlining, add
`--inline` to `perf report` when debuginfo is available.

Off-CPU time, run-queue delay, and disk or network waits come from the
`linux-ebpf-io-network` skill's `bpf-capture.sh` (operator-run). BCC stack
tools walk frame pointers only, so `offcputime` and `profile` stacks
truncate in code built without `-fno-omit-frame-pointer`, whatever perf's
DWARF mode could do.

Without ptrace or perf access, `/proc` still shows each thread's state and
wait channel, readable as the same user:

```bash
for t in /proc/"$PID"/task/*; do
  printf '%s %s %s\n' "${t##*/}" "$(cut -d' ' -f3 "$t/stat")" "$(cat "$t/wchan")"
done
```

Memory: compare `/proc/PID/smaps_rollup` and `/proc/PID/status`
(`VmRSS`, `RssAnon`, `RssFile`) over time, and note major-fault counts from
`perf stat`. For glibc arena growth, list the process's tunables with
`/lib64/ld-linux-x86-64.so.2 --list-tunables` (`glibc.malloc.arena_max`);
changing them needs a restart and is an experiment, not triage.

Crash: read `/proc/sys/kernel/core_pattern` to find where cores go (a
`systemd-coredump` or `apport` pipe, or a file pattern), then analyse offline
with the binary and debuginfo that match the core's build-id:

```bash
gdb -batch -ex 'thread apply all bt' ./server ./core
```

## Symptom map

| Symptom / first evidence | Next step | First question |
| --- | --- | --- |
| Stacks show `[unknown]` or hex, or stop after 1–2 frames | `cpp-build-readiness` | Symbols, matching debuginfo, and frame pointers or DWARF unwinding? |
| p99/p99.9 spikes, periodic stalls | `java-latency-measurement` method, then `linux-low-latency-tuning` | Are spikes real (CO-free), and do they align with host events? |
| Spikes with the hot thread off-CPU | `linux-ebpf-io-network` (offcputime, runqlat) | Preempted, blocked on a futex, or waiting on I/O? |
| High CPU, throughput plateau | perf on-CPU capture above | Which DSOs and functions own CPU at saturation? |
| Much time in `malloc`/`free` or `futex` under load | perf on-CPU plus `perf trace -s` | Allocator contention or a lock? Which call sites? |
| RSS grows with no workload change | `/proc` memory series above | Anonymous or file-backed growth; allocator retention or a leak? |
| Slower after a deploy or rebuild | `cpp-build-readiness` on both builds | Did optimisation, `-march`, LTO, or allocator flags change? |
| Low IPC, cache or branch misses suspected | `java-hardware-counters` | Which PMU evidence supports a memory-bound hypothesis? |
| Contended writes, poor scaling with threads | `java-cache-efficiency` (`perf c2c`), `java-numa-affinity` | False sharing, SMT siblings, or cross-domain traffic? |
| fsync, disk, or page-fault latency | `linux-ebpf-io-network` | Which syscalls or block I/O dominate the tail? |
| Network latency, drops, retransmits | `linux-ebpf-io-network` | Drops, buffer overflow, coalescing, or application backlog? |
| Periodic stalls in containers | `profiling-readiness` (`container-readiness.py`) | Is the CFS quota throttling the process? |
| Hung process | `/proc` thread states above, then approved gdb | Which threads wait, on what, and since when? |
| Crash or restart | Core file and journal, offline gdb | What signal, which thread, and does the build-id match the debuginfo? |
| Native frames hot in a JVM's profile | Here, with `cpp-build-readiness` on the JNI library | Is the native library itself slow, or called too often from Java? |
