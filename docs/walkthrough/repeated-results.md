# Repeated unprofiled walkthrough runs

Synthetic in-process workload; real, unedited report output. Recorded 2026-09-13
on the development Linux host, Temurin 25.0.2. Both modes use G1, a fixed
64 MiB heap, identical GC logging, 20 seconds, and 10,000 operations/second.
Neither mode records JFR. Order alternates across pairs. These 200,000-sample
runs make p99.99 indicative, not a validated SLO. This is an unisolated desktop;
CPU affinity and background host activity were not controlled. No test JVMs were
intentionally run alongside this recorded series.

Run 1, allocating
```text
response_time: n=200000 p50=97ns p90=178ns p99=384ns p99.9=17.236us p99.99=2.282ms max=3.244ms
note: fewer than 100 tail samples; indicative only: p99.99
service_time : n=200000 p50=80ns p90=161ns p99=351ns p99.9=1.342us p99.99=10.130us max=3.244ms
queue_delay  : n=200000 p50=16ns p90=29ns p99=39ns p99.9=15.703us p99.99=2.182ms max=3.144ms
intended_rate_per_s=10000.0 achieved_completion_rate_per_s=10000.0
response/service ratio: p99=1.09 p99.9=12.84 p99.99=225.30  <- queueing at p99.99: service-time-only reporting would hide this
p99_across_10_blocks: min=223ns median=393ns max=464ns
```

Run 1, zero-alloc
```text
response_time: n=200000 p50=57ns p90=75ns p99=102ns p99.9=270ns p99.99=28.862us max=759.957us
note: fewer than 100 tail samples; indicative only: p99.99
service_time : n=200000 p50=40ns p90=51ns p99=80ns p99.9=200ns p99.99=662ns max=5.640us
queue_delay  : n=200000 p50=16ns p90=29ns p99=38ns p99.9=42ns p99.99=28.802us max=759.005us
intended_rate_per_s=10000.0 achieved_completion_rate_per_s=10000.0
response/service ratio: p99=1.27 p99.9=1.35 p99.99=43.60  <- queueing at p99.99: service-time-only reporting would hide this
p99_across_10_blocks: min=87ns median=98ns max=126ns
```

Run 2, zero-alloc
```text
response_time: n=200000 p50=57ns p90=73ns p99=102ns p99.9=388ns p99.99=34.202us max=221.462us
note: fewer than 100 tail samples; indicative only: p99.99
service_time : n=200000 p50=40ns p90=50ns p99=80ns p99.9=300ns p99.99=1.152us max=7.494us
queue_delay  : n=200000 p50=16ns p90=29ns p99=38ns p99.9=40ns p99.99=34.162us max=221.072us
intended_rate_per_s=10000.0 achieved_completion_rate_per_s=10000.0
response/service ratio: p99=1.27 p99.9=1.29 p99.99=29.69  <- queueing at p99.99: service-time-only reporting would hide this
p99_across_10_blocks: min=88ns median=100ns max=150ns
```

Run 2, allocating
```text
response_time: n=200000 p50=97ns p90=168ns p99=404ns p99.9=149.949us p99.99=1.941ms max=2.773ms
note: fewer than 100 tail samples; indicative only: p99.99
service_time : n=200000 p50=80ns p90=150ns p99=370ns p99.9=2.595us p99.99=9.688us max=2.773ms
queue_delay  : n=200000 p50=16ns p90=29ns p99=39ns p99.9=137.808us p99.99=1.841ms max=2.673ms
intended_rate_per_s=10000.0 achieved_completion_rate_per_s=10000.0
response/service ratio: p99=1.09 p99.9=57.78 p99.99=200.37  <- queueing at p99.99: service-time-only reporting would hide this
p99_across_10_blocks: min=343ns median=392ns max=486ns
```

Run 3, allocating
```text
response_time: n=200000 p50=97ns p90=173ns p99=487ns p99.9=253.601us p99.99=2.138ms max=3.136ms
note: fewer than 100 tail samples; indicative only: p99.99
service_time : n=200000 p50=80ns p90=160ns p99=420ns p99.9=6.252us p99.99=17.964us max=3.136ms
queue_delay  : n=200000 p50=16ns p90=29ns p99=39ns p99.9=238.796us p99.99=2.051ms max=3.036ms
intended_rate_per_s=10000.0 achieved_completion_rate_per_s=10000.1
response/service ratio: p99=1.16 p99.9=40.56 p99.99=119.03  <- queueing at p99.99: service-time-only reporting would hide this
p99_across_10_blocks: min=323ns median=501ns max=2.161us
```

Run 3, zero-alloc
```text
response_time: n=200000 p50=57ns p90=74ns p99=116ns p99.9=2.557us p99.99=242.594us max=937.694us
note: fewer than 100 tail samples; indicative only: p99.99
service_time : n=200000 p50=40ns p90=51ns p99=81ns p99.9=361ns p99.99=1.362us max=21.911us
queue_delay  : n=200000 p50=16ns p90=29ns p99=39ns p99.9=1.904us p99.99=242.564us max=937.414us
intended_rate_per_s=10000.0 achieved_completion_rate_per_s=10000.2
response/service ratio: p99=1.43 p99.9=7.08 p99.99=178.12  <- queueing at p99.99: service-time-only reporting would hide this
p99_across_10_blocks: min=91ns median=114ns max=191ns
```
