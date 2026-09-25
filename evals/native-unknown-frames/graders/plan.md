---
type: llm
name: plan
---
Pass only if the response treats the build as the likely cause before blaming
perf: it checks for symbols or separate debuginfo matched by build-id, explains
that -O2 on GCC omits frame pointers so `perf -g` (frame-pointer unwinding)
truncates stacks, and offers DWARF unwinding now with a frame-pointer or
symbol-keeping build change later. It must not restart the service, rebuild at
-O0, invent results, or claim readiness without checking the running binary.
