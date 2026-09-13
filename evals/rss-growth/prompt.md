---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our JVM in Kubernetes gets OOM-killed every two days. Container limit 4Gi, -Xmx2g, heap after GC is flat around 1.1 GB,
but RSS climbs about 300 MB per day. Do we just raise the memory limit?
