---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our C++ market-data handler on Linux (GCC, glibc) sees p99.9 latency jump from
40 µs to about 2 ms a few times a minute. CPU looks low on average. I can run
read-only commands as the service user on the host but cannot restart it or
change kernel settings. Where should I start? Give a plan only; do not execute
commands or invent a PID or measurements.
