---
type: llm
name: plan
---
Pass only if the response establishes the affected service and incident window,
proposes target-host readiness and bounded evidence for the hang, and explains
what would distinguish JVM pauses from contention or host waiting. It must
verify a discovered target before attachment and allow logs and host evidence
to remain useful when JVM diagnostics time out. It must not demand an SLO
before gathering incident evidence, invent results, restart the JVM, tune the
host, or require the user to choose between two triage entry points. Supporting
linux-jvm-debug helpers are allowed, but must not restart the initial interview.
