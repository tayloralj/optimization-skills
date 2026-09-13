# Verifying low-latency changes

## Zero allocation

1. **Probe** a hot path in isolation (no dependencies):

   ```java
   public final class EncodeOrder implements Runnable {
       private final byte[] buffer = new byte[64];
       private final OrderFlyweight order = new OrderFlyweight();
       private long id;
       @Override public void run() {
           order.wrap(buffer, 0).orderId(++id).priceTicks(101_250L).quantity(10);
       }
   }
   ```

   ```bash
   java -cp target/classes scripts/AllocationProbe.java EncodeOrder
   # bytes_per_op_last_round=0.0000  result=PASS   (exit code 0)
   ```

   It warms up (2 million operations by default), then measures the calling
   thread's allocated bytes over several rounds. Every measured round must meet
   the budget; increase warmup separately if compilation has not stabilised. Use `--max-bytes-per-op` to set
   a budget and wire it into CI.

2. **JMH** with `-prof gc`: `gc.alloc.rate.norm` should be ≈ 0 bytes/op for the
   benchmark method (see the `java-jmh-benchmarking` skill).

3. **Soak**: run the service under representative load for longer than the
   young-GC interval you care about, with GC logging. After warmup,
   `gc-log-summary.py` (the `java-gc-tuning` skill) should show no pauses, or a
   rate that matches only known cold-path work.

4. **JFR**: `jfr view allocation-by-site` on hot threads should be empty after warmup.

A result applies to this JDK, flags, and input shape. Re-check after JDK
upgrades, dependency updates, and changes in inlining.

## Concurrency correctness with JCStress

Any hand-written concurrent structure needs a stress test that explores
interleavings. Create a project from the official archetype
(`org.openjdk.jcstress:jcstress-java-test-archetype`, pinned version), then:

```java
@JCStressTest
@Outcome(id = {"0, 1", "1, 1"}, expect = Expect.ACCEPTABLE, desc = "value delivered exactly once")
@Outcome(expect = Expect.FORBIDDEN, desc = "value lost or duplicated")
@State
public class SpscRingStress {
    private final SpscLongRing ring = new SpscLongRing(4);
    private int consumed;

    @Actor
    public void producer() {
        ring.offer(42L);
    }

    @Actor
    public void consumer(II_Result r) {
        if (ring.poll(v -> consumed++)) {
            r.r1 = 1;
        }
    }

    @Arbiter
    public void drain(II_Result r) {
        while (ring.poll(v -> consumed++)) {
            // drain what the consumer actor missed
        }
        r.r2 = consumed;
    }
}
```

Run with `java -jar target/jcstress.jar -t SpscRingStress`. Also test full and
empty boundaries, wrap-around, and (for multi-producer designs) two producers.
Run on the deployment CPU architecture; memory-ordering behaviour differs.

## Latency

- Compare before/after with open-loop load and full histograms (the
  `java-latency-measurement` skill); a microbenchmark gain is not a latency result.
- Run `JitterMeter.java --mode spin` on the target core to know the platform
  noise floor before attributing small tail changes to code.

## Review checklist for a hot-path change

- [ ] Threading contract written down and unchanged (or intentionally changed and stress-tested)
- [ ] Allocation probe or `-prof gc` shows the intended bytes/op
- [ ] JCStress for any new or modified concurrent structure
- [ ] Open-loop latency histograms before/after, repeated
- [ ] Soak with GC logging, no unexpected collections
- [ ] Failure paths (full queue, malformed message, slow consumer) tested
- [ ] Rollback path (feature flag or previous build) available
