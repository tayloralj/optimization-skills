import java.io.IOException;
import java.io.PrintStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;

/**
 * Platform jitter ("hiccup") meter. No dependencies; run with the JDK source launcher:
 *
 *   java scripts/JitterMeter.java --mode spin --duration 60 --threshold-us 20
 *   taskset -c 5 java -Xms64m -Xmx64m scripts/JitterMeter.java --mode sleep --interval-us 1000
 *
 * spin:  a thread busy-spins on System.nanoTime and records gaps between consecutive
 *        reads. Gaps are time the thread did not run: preemption, interrupts, SMIs,
 *        safepoints, GC, page faults. Run on the CPU you intend for a hot thread.
 * sleep: parks for an interval and records wake-up overshoot (timer slack, idle exit,
 *        scheduler latency). Models a thread that blocks between events.
 *
 * The measuring loop does not allocate. Output: percentiles, counts above thresholds,
 * and the worst events with JVM uptime so they can be aligned with GC/safepoint logs.
 * The meter observes interference; it is not a load test and not a substitute for
 * measuring the application itself.
 */
public final class JitterMeter {
    private static final int SUB_BITS = 5;
    private static final int SUB_COUNT = 1 << SUB_BITS;
    private static final int WORST = 16;

    private final long[] counts = new long[64 * SUB_COUNT];
    private long total;
    private long max;
    private final long[] worstValue = new long[WORST];
    private final long[] worstAtNanos = new long[WORST];

    static int index(long value) {
        if (value < SUB_COUNT) {
            return (int) Math.max(value, 0);
        }
        int exponent = 63 - Long.numberOfLeadingZeros(value);
        int shift = exponent - SUB_BITS;
        int sub = (int) ((value >>> shift) & (SUB_COUNT - 1));
        return SUB_COUNT + shift * SUB_COUNT + sub;
    }

    static long upperBound(int index) {
        if (index < SUB_COUNT) {
            return index;
        }
        int shift = (index - SUB_COUNT) / SUB_COUNT;
        int sub = (index - SUB_COUNT) % SUB_COUNT;
        return (((long) (SUB_COUNT + sub + 1)) << shift) - 1;
    }

    void record(long valueNanos, long atNanos) {
        counts[index(valueNanos)]++;
        total++;
        if (valueNanos > max) {
            max = valueNanos;
        }
        int smallest = 0;
        for (int i = 1; i < WORST; i++) {
            if (worstValue[i] < worstValue[smallest]) {
                smallest = i;
            }
        }
        if (valueNanos > worstValue[smallest]) {
            worstValue[smallest] = valueNanos;
            worstAtNanos[smallest] = atNanos;
        }
    }

    long percentile(double pct) {
        long rank = Math.max(1, (long) Math.ceil(pct / 100.0 * total));
        long seen = 0;
        for (int i = 0; i < counts.length; i++) {
            seen += counts[i];
            if (seen >= rank) {
                return Math.min(upperBound(i), max);
            }
        }
        return max;
    }

    long countAbove(long thresholdNanos) {
        long n = 0;
        for (int i = 0; i < counts.length; i++) {
            if (upperBound(i) > thresholdNanos) {
                n += counts[i];
            }
        }
        return n;
    }

    public static void main(String[] args) throws IOException, InterruptedException {
        String mode = "spin";
        long durationSeconds = 30;
        long intervalMicros = 1000;
        long thresholdMicros = 20;
        long warmupSeconds = 5;
        Path out = null;
        for (int i = 0; i < args.length; i++) {
            String arg = args[i];
            String value = i + 1 < args.length ? args[i + 1] : null;
            switch (arg) {
                case "--mode" -> { mode = require(arg, value); i++; }
                case "--duration" -> { durationSeconds = parse(arg, value, 1, 86_400); i++; }
                case "--warmup" -> { warmupSeconds = parse(arg, value, 0, 3_600); i++; }
                case "--interval-us" -> { intervalMicros = parse(arg, value, 1, 10_000_000); i++; }
                case "--threshold-us" -> { thresholdMicros = parse(arg, value, 1, 10_000_000); i++; }
                case "--out" -> { out = Path.of(require(arg, value)); i++; }
                case "-h", "--help" -> { usage(System.out); return; }
                default -> { usage(System.err); System.exit(2); }
            }
        }
        if (!mode.equals("spin") && !mode.equals("sleep")) {
            usage(System.err);
            System.exit(2);
        }
        if (out != null && Files.exists(out)) {
            System.err.println("output exists; refusing to overwrite: " + out);
            System.exit(4);
        }

        JitterMeter meter = new JitterMeter();
        long start = System.nanoTime();
        long measureFrom = start + warmupSeconds * 1_000_000_000L;
        long end = measureFrom + durationSeconds * 1_000_000_000L;
        if (mode.equals("spin")) {
            spin(meter, measureFrom, end);
        } else {
            sleep(meter, measureFrom, end, intervalMicros * 1_000L);
        }
        report(meter, mode, durationSeconds, warmupSeconds, intervalMicros, thresholdMicros, start, out);
    }

    private static void spin(JitterMeter meter, long measureFrom, long end) {
        long previous = System.nanoTime();
        while (previous < end) {
            long now = System.nanoTime();
            if (now >= measureFrom) {
                meter.record(now - previous, now);
            }
            previous = now;
        }
    }

    private static void sleep(JitterMeter meter, long measureFrom, long end, long intervalNanos) {
        long next = System.nanoTime() + intervalNanos;
        while (next < end) {
            long delay = next - System.nanoTime();
            if (delay > 0) {
                java.util.concurrent.locks.LockSupport.parkNanos(delay);
            }
            long woke = System.nanoTime();
            if (woke >= measureFrom) {
                meter.record(Math.max(0, woke - next), woke);
            }
            next += intervalNanos;
            if (woke > next) {
                next = woke + intervalNanos; // do not replay missed wake-ups as a burst
            }
        }
    }

    private static void report(JitterMeter m, String mode, long duration, long warmup, long intervalMicros,
                               long thresholdMicros, long startNanos, Path out) throws IOException {
        StringBuilder sb = new StringBuilder();
        sb.append(String.format(Locale.ROOT, "mode=%s duration_s=%d warmup_s=%d%s%n", mode, duration, warmup,
                mode.equals("sleep") ? " interval_us=" + intervalMicros : ""));
        sb.append(String.format(Locale.ROOT, "jvm=%s %s%n", System.getProperty("java.vm.version"),
                System.getProperty("java.vm.name")));
        sb.append(String.format(Locale.ROOT, "available_processors=%d%n", Runtime.getRuntime().availableProcessors()));
        sb.append(String.format(Locale.ROOT, "samples=%d%n", m.total));
        String[] labels = {"p50", "p90", "p99", "p99.9", "p99.99", "p99.999"};
        double[] pcts = {50, 90, 99, 99.9, 99.99, 99.999};
        for (int i = 0; i < pcts.length; i++) {
            sb.append(String.format(Locale.ROOT, "%s_us=%.3f%n", labels[i], m.percentile(pcts[i]) / 1000.0));
        }
        sb.append(String.format(Locale.ROOT, "max_us=%.3f%n", m.max / 1000.0));
        for (long t : new long[] {thresholdMicros, 100, 1_000, 10_000}) {
            sb.append(String.format(Locale.ROOT, "count_above_%dus=%d%n", t, m.countAbove(t * 1_000L)));
        }
        sb.append("worst_events (value_us at jvm_uptime_ms):\n");
        Integer[] order = new Integer[WORST];
        for (int i = 0; i < WORST; i++) {
            order[i] = i;
        }
        java.util.Arrays.sort(order, (a, b) -> Long.compare(m.worstValue[b], m.worstValue[a]));
        long uptimeOffsetMs = java.lang.management.ManagementFactory.getRuntimeMXBean().getUptime()
                - (System.nanoTime() - startNanos) / 1_000_000L;
        for (int i : order) {
            if (m.worstValue[i] > 0) {
                sb.append(String.format(Locale.ROOT, "  %.3f at %d%n", m.worstValue[i] / 1000.0,
                        uptimeOffsetMs + (m.worstAtNanos[i] - startNanos) / 1_000_000L));
            }
        }
        if (m.total > 0 && m.total < 100_000) {
            sb.append("note: fewer than 100000 samples; p99.99 and above are not meaningful\n");
        }
        System.out.print(sb);
        if (out != null) {
            Files.writeString(out, sb.toString());
        }
    }

    private static String require(String name, String value) {
        if (value == null) {
            System.err.println(name + " needs a value");
            System.exit(2);
        }
        return value;
    }

    private static long parse(String name, String value, long min, long max) {
        try {
            long v = Long.parseLong(require(name, value));
            if (v < min || v > max) {
                throw new NumberFormatException();
            }
            return v;
        } catch (NumberFormatException e) {
            System.err.println(name + " must be an integer in [" + min + ", " + max + "]");
            System.exit(2);
            return 0;
        }
    }

    private static void usage(PrintStream s) {
        s.println("Usage: java JitterMeter.java [--mode spin|sleep] [--duration S] [--warmup S]"
                + " [--interval-us N] [--threshold-us N] [--out FILE]");
    }
}
