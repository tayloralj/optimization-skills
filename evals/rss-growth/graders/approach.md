---
type: llm
weight: 2
---

The response should advise against simply raising the limit before the growth is explained. It should propose enabling Native
Memory Tracking (restart with -XX:NativeMemoryTracking=summary), taking snapshots over time, and comparing NMT categories with RSS,
and list plausible non-heap owners (for example direct or mapped buffers, threads, metaspace or class loading, code cache,
glibc malloc arenas or native libraries). It should mention checking cgroup memory evidence (memory.events oom_kill or memory.stat).
Fail if it only suggests raising -Xmx or the container limit.
