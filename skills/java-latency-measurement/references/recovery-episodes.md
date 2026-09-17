# Recovery episodes: gap fill, replay, reconnect, catch-up

Recovery code runs rarely, so fixed-rate latency tests barely exercise it and
batch timings of one large recovery miss its failure modes. Treat each fault
and the recovery that follows as one **episode**, and measure many of them
under live load.

## Load model

- An open-loop live feed at a fixed rate, from its own thread or process,
  with intended send times computed from a schedule.
- A **seeded** fault schedule layered on top: losses, disconnects, or
  restarts, with sizes drawn from a stated mix (for example 1, 10, 100, 1000,
  and 10000 messages). The seed makes a failing run repeatable.
- Include faults that start **right after** the previous recovery finishes, and
  faults that arrive **during** a recovery. State-machine bugs live at those
  boundaries; a schedule of isolated faults will not find them.
- Hundreds or thousands of episodes per configuration, across several fresh
  JVMs. Five recoveries of one fault size per JVM is a smoke test.
- Sweep the variables that change protocol behaviour: live rate, round-trip
  time (`scripts/TcpDelayProxy.java` when `tc netem` is not allowed), and fault
  size relative to any server chunk or batch limit.

## When the clock starts

A lost message cannot be repaired before its loss is observable. Record, per
episode:

| Timestamp | Meaning |
| --- | --- |
| intended | when the fault became observable (for a loss: the intended send time of the first message after it) |
| actual | when the system detected it |
| end | when recovery completed (last missing item delivered, or live delivery resumed) |

`actual - intended` is detection delay; `end - actual` is repair time. Feed
these as `intended,actual,end,group` rows to `latency-report.py --episodes`.

Measuring repaired messages from their own intended send time mixes in how
long the fault lasted. A 10,000-message loss at 20,000 msg/s is half a second
of silence before anything can be detected; that is not repair latency.

Dropped traffic is also idle time for the receiver. Idle-wait effects (select
timeouts, wake-up latency) then appear only in runs with faults. Compare
against a no-fault control and a busy-poll control before blaming the
recovery code.

## What to record per episode

- Completion: did it finish? Count stalled episodes; any stall invalidates
  the latency result (see the completeness gate in the skill).
- Work amplification: requests, round trips, reconnects, and bytes per
  episode. A recovery that re-requests data it already holds can look fast on
  loopback and collapse under real RTT or higher rates. Count before you
  profile; profilers show where CPU goes, not how many round trips were made.
- Timeouts, retries, and stalls, with their reasons.
- Effect on live traffic: latency of live messages delivered during and after
  each episode, from their intended send time.

## Reporting

- Per configuration: episodes, stalls, requests per episode (mean and max),
  and detection, repair, and total time per fault-size group.
- Live-traffic percentiles with and without faults, from the same harness.
- The fault seed, schedule parameters, rate, RTT, and repetitions.
- Keep completion-time claims (how long a recovery took) separate from
  latency claims (what live traffic experienced).
