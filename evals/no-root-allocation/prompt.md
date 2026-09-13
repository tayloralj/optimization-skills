---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Production JVM (JDK 25, Ubuntu). `perf record` fails with "Access to performance monitoring and observability operations is limited"
and perf_event_paranoid is 4. I don't have root and can't restart the service today. I need to know which code allocates the most.
What do I do?
