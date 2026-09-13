---
type: llm
weight: 2
---

The response should clearly say no, or not yet: a JMH SampleTime result does not establish service tail latency.
It should explain at least two of: closed-loop measurement hides queueing (coordinated omission); a microbenchmark omits
real costs (I/O, serialization, GC interaction, other threads, OS jitter); and p99.99 needs many samples under representative load.
It should recommend an open-loop, fixed-rate test that measures from intended start time with full histograms, run on representative
hardware, before committing to an SLA. Fail if it endorses the SLA number.
