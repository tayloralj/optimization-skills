---
type: llm
name: plan
---
Pass only if the response first checks that the latency measurement is valid
(coordinated omission or histogram method), checks build readiness (symbols,
frame pointers or DWARF unwinding) and host profiling readiness before
profiling, and separates on-CPU hot-path cost from off-CPU waiting, run-queue
delay, interrupts, and page faults using bounded captures. It must warn that
gdb attach or gcore stops the process, must not restart the service or tune
the kernel, must not blame garbage collection or other JVM mechanisms, and must
not invent results.
