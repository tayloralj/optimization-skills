---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our C++ order router runs on Ubuntu, built with GCC at -O2 and deployed as a
stripped binary. `perf record -g` on it shows most samples under `[unknown]`
or raw hex addresses, and stacks stop after one or two frames. I can run
read-only commands as the service user but cannot restart it today. What should
I check before profiling again? Give a plan only; do not execute commands or
invent a PID or results.
