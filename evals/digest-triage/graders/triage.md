---
type: llm
weight: 2
---

Pass if the response reads the digest as pointing at CPU starvation rather than GC: the hot handler threads waited
roughly 13-14% of the window for a CPU (about 40 s of run-queue delay in 300 s), CPU pressure is high, hypervisor steal
is 11.8% overall and near 30% in the busiest intervals, while GC pauses are tiny (max 3.1 ms, 0.02% of wall time) and
there was no cgroup throttling. Next steps should include host or hypervisor evidence and placement (dedicated or
isolated vCPUs, noisy neighbours, the `linux-low-latency-tuning` skill), a baseline comparison, and confirming with
the full bundle when it arrives. It should treat the digest as leads, not proof.
Fail if the main recommendation is GC or heap tuning, if it claims the cause is proven from the digest alone, or if it
invents numbers not in the digest.
