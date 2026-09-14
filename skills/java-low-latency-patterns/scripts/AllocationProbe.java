import java.lang.management.ManagementFactory;
import java.util.Locale;

/**
 * Measures heap bytes allocated per operation by a hot path after JIT warmup.
 * No dependencies; run with the JDK source launcher and your classes on the class path:
 *
 *   java -cp target/classes scripts/AllocationProbe.java com.example.EncodeOrder
 *   java -cp app.jar scripts/AllocationProbe.java com.example.EncodeOrder --ops 2000000 --max-bytes-per-op 0
 *
 * The target class must implement Runnable and have a public no-argument constructor;
 * each run() call is one operation and should reuse state set up in the constructor.
 * Exit code 0 when the measured bytes/op is at most --max-bytes-per-op (default 0), 1
 * otherwise, so it can gate CI. It measures the calling thread only
 * (com.sun.management.ThreadMXBean), after warmup so C2 escape analysis has run.
 * A zero result is evidence for this JVM, flags, and input shape - not a guarantee.
 */
public final class AllocationProbe {
    public static void main(String[] args) throws Exception {
        if (args.length == 0 || args[0].equals("-h") || args[0].equals("--help")) {
            System.out.println("Usage: java -cp CLASSPATH AllocationProbe.java CLASS [--warmup-ops N] [--ops N] [--rounds N] [--max-bytes-per-op B]");
            System.exit(args.length == 0 ? 2 : 0);
        }
        String className = args[0];
        long warmupOps = 2_000_000;
        long ops = 1_000_000;
        int rounds = 5;
        double maxBytesPerOp = 0.0;
        for (int i = 1; i < args.length; i += 2) {
            if (i + 1 >= args.length) {
                fail(args[i] + " needs a value");
            }
            switch (args[i]) {
                case "--warmup-ops" -> warmupOps = positive(args[i], args[i + 1]);
                case "--ops" -> ops = positive(args[i], args[i + 1]);
                case "--rounds" -> rounds = (int) Math.min(100, positive(args[i], args[i + 1]));
                case "--max-bytes-per-op" -> maxBytesPerOp = Double.parseDouble(args[i + 1]);
                default -> fail("unknown option " + args[i]);
            }
        }

        if (!Double.isFinite(maxBytesPerOp) || maxBytesPerOp < 0) {
            fail("--max-bytes-per-op must be finite and non-negative");
        }
        Object instance = Class.forName(className).getDeclaredConstructor().newInstance();
        if (!(instance instanceof Runnable task)) {
            fail(className + " must implement Runnable");
            return;
        }
        var threads = (com.sun.management.ThreadMXBean) ManagementFactory.getThreadMXBean();
        if (!threads.isThreadAllocatedMemorySupported() || !threads.isThreadAllocatedMemoryEnabled()) {
            fail("thread allocated-memory measurement is not available on this JVM");
        }

        runOperations(task, warmupOps);
        // Prime the measurement call itself so it does not count toward round one.
        threads.getCurrentThreadAllocatedBytes();

        double worst = 0;
        double last = 0;
        double[] measurements = new double[rounds];
        for (int r = 0; r < rounds; r++) {
            long before = threads.getCurrentThreadAllocatedBytes();
            runOperations(task, ops);
            long after = threads.getCurrentThreadAllocatedBytes();
            last = (double) (after - before) / ops;
            worst = Math.max(worst, last);
            measurements[r] = last;
        }

        StringBuilder perRound = new StringBuilder();
        for (int r = 0; r < rounds; r++) {
            perRound.append(String.format(Locale.ROOT, "%s%.4f", r == 0 ? "" : ",", measurements[r]));
        }
        System.out.printf(Locale.ROOT, "class=%s%n", className);
        System.out.printf(Locale.ROOT, "jvm=%s%n", System.getProperty("java.vm.version"));
        System.out.printf(Locale.ROOT, "warmup_ops=%d ops_per_round=%d rounds=%d%n", warmupOps, ops, rounds);
        System.out.printf(Locale.ROOT, "bytes_per_op_by_round=%s%n", perRound);
        System.out.printf(Locale.ROOT, "bytes_per_op_last_round=%.4f%n", last);
        System.out.printf(Locale.ROOT, "bytes_per_op_worst_round=%.4f%n", worst);
        boolean pass = worst <= maxBytesPerOp;
        System.out.printf(Locale.ROOT, "result=%s (threshold %.4f bytes/op in every measured round)%n",
                pass ? "PASS" : "FAIL", maxBytesPerOp);
        if (!pass && worst > last) {
            System.out.println("note: measured rounds differ; check periodic paths and warmup separately");
        }
        System.exit(pass ? 0 : 1);
    }

    private static void runOperations(Runnable task, long count) {
        for (long i = 0; i < count; i++) task.run();
    }

    private static long positive(String name, String value) {
        try {
            long v = Long.parseLong(value);
            if (v > 0) {
                return v;
            }
        } catch (NumberFormatException ignored) {
            // fall through
        }
        fail(name + " must be a positive integer");
        return 0;
    }

    private static void fail(String message) {
        System.err.println(message);
        System.exit(2);
    }
}
