---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill]
---

Ops could only paste this text from the offline collector on our trading gateway VM (Java 21). The full bundle is
stuck in a file-transfer queue for two days. What does it tell us about tonight's p99 spikes, and what next?

```text
# JVM capture digest: jvmcap-host-1a2b3c4d-4242-20260915T180102Z (kit 0.3.0)
host=host-1a2b3c4d
arch=x86_64
pid=4242
logical_cpus=8
duration_s=300
trigger_fired=immediate
jcmd_source=jdk
target_mount_ns=same
interrupted=0
target_alive_at_end=yes
OpenJDK 64-Bit Server VM version 21.0.5+11-LTS

## Threads by CPU over 300.4 s (top 15)

cpu_pct	run_delay_ms	thread (tid)
97.6	41250.3	md-handler-1 (4260)
95.1	38804.9	md-handler-2 (4261)
22.4	3120.5	order-sender (4270)
2.0	410.2	G1 Conc#0 (4251)
1.1	95.0	GC Thread#0 (4249)

## Host CPU over the window

user 61.0% system 4.1% iowait 0.2% irq+softirq 1.1% steal 11.8% idle 21.8%
pressure cpu some 14.20% of the window
pressure io some 0.02% of the window
pressure memory some 0.00% of the window
cgroup throttled 0 times, 0.0 ms during the window

## Busiest sample intervals (process CPU % of one core)

81203.4-81208.4 s host uptime: process 231%, host steal 29.6%, iowait 0.1%
81503.1-81508.1 s host uptime: process 229%, host steal 27.9%, iowait 0.2%
81353.6-81358.6 s host uptime: process 226%, host steal 3.1%, iowait 0.1%

## Host audit findings

finding=info:governor:governor(s) performance on checked CPUs
finding=info:thp_enabled:transparent hugepages always

## GC during the window

collectors: G1
pauses_ms: n=41 sum=58.400 p50=1.200 p90=2.100 p99=3.100 p99.9=3.100 max=3.100
pause_fraction: 0.019% of wall time
time_to_safepoint_ms: n=60 sum=1.200 p50=0.010 p90=0.030 p99=0.080 p99.9=0.080 max=0.080
```

(The digest above is synthetic, written for this evaluation.)
