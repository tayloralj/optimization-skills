---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our Java market-data client repairs UDP gaps over TCP. We benchmarked recovery by starting a JVM, dropping
one 250,000-message range, and timing the repair five times per JVM on loopback: median 44 ms, every run passed.
Separately, our latency histogram for live messages during a 30-second soak with random loss looks fine
(p99 = 40 µs). Is gap fill production-ready? What would you check before saying yes? Do not run commands.
