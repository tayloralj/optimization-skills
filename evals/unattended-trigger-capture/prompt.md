---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our Java 25 order router on a production VM runs as user `router`, already with GC logging and
`-XX:StartFlightRecording=name=continuous,maxage=30m`. Once a night, at an unpredictable time, CPU jumps and p99
latency spikes for a few minutes. Nobody is awake then, Claude and Codex cannot run on that box, and ops will run
one thing we send them during the day and send files back the next morning. How do we capture the next spike and
analyse it here?
