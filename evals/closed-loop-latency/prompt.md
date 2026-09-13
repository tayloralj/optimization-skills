---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our JMH benchmark of the order handler in SampleTime mode reports p99 = 48 µs and p99.99 = 90 µs.
So the service's p99.99 must be under 100 µs in production, right? We want to put that in the SLA.
