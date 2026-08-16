# Evidence-to-pattern map

| Evidence | Candidate | Required checks |
| --- | --- | --- |
| Allocation profile identifies short-lived buffers | Reuse, batch, scalarize, or right-size | Ownership, clearing, retained capacity, native/heap accounting |
| Multi-writer counter CAS contention | `LongAdder`, stripes, local aggregation | Exactness, read freshness, reset semantics |
| Single-writer metric atomics are measured hot | Plain owner field plus periodic volatile snapshot | Visibility lag, overflow, scrape semantics, shutdown flush |
| Read-mostly subscriber list serializes publishers | Volatile publication of a defensive array/list copy that is never mutated afterward | Publication safety, removal, ordering, mutation frequency |
| Lock profile shows long critical section | Reduce protected work or change ownership | Correctness, exception path, memory visibility, fairness |
| Copy/serialization dominates | Batch, encode once, gather write; direct buffer only when it removes a measured heap/native copy and the consumer can reuse it | Backpressure, partial writes, buffer lifetime, native memory, max payload |
| Clock/native downcall dominates | Coarser timestamp, cached clock, fewer reads | Clock semantics, monotonicity, audit precision, failure recovery |
| Queue hand-off dominates | Batch, single-writer ownership, suitable bounded queue | Capacity, wakeup policy, backpressure, ordering, failover |
| Cache-line contention is proven | Separate fields/owners, `@Contended`, redesign writes | JOL layout, JVM flag, footprint, GC movement, topology |

Source patterns are hypotheses. Confirm them with a profile or a
production-faithful benchmark, then verify the candidate against the user-facing
metric. Avoid universal percentage-gain claims.
