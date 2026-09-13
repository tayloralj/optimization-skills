---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our trading gateway (JDK 21, G1, -Xmx2g) shows latency spikes. Here is an excerpt of the GC log
from the busy hour. Are GC pauses the problem, and what should we do first?

```
[3600.101s][info][gc] GC(812) Pause Young (Normal) (G1 Evacuation Pause) 1820M->1790M(2048M) 14.212ms
[3600.402s][info][gc] GC(813) Pause Young (Normal) (G1 Evacuation Pause) (Evacuation Failure: Allocation) 2010M->2002M(2048M) 38.901ms
[3600.455s][info][gc] GC(814) Pause Full (G1 Compaction Pause) 2040M->1410M(2048M) 912.442ms
[3601.020s][info][gc] GC(815) Pause Young (Normal) (G1 Humongous Allocation) 1650M->1600M(2048M) 11.030ms
[3601.021s][info][safepoint] Safepoint "G1CollectForAllocation", Time since last: 553000000 ns, Reaching safepoint: 190000 ns, Cleanup: 12000 ns, At safepoint: 11100000 ns, Total: 11302000 ns
```
