import java.lang.management.ManagementFactory;
import java.util.Locale;
import java.util.Random;
import java.util.concurrent.locks.LockSupport;

/** Synthetic profiler attribution fixture, not a benchmark or application model. */
public final class VendorWorkload {
    private static final int OPS_PER_BATCH = 1024;
    private static volatile Object escaped;
    private static volatile long sink;
    private final int[] data;
    private final Object monitor = new Object();
    private int cursor;
    private long sequence;

    private VendorWorkload(String mode, int mib) {
        data = new int[mib * 1024 * 1024 / Integer.BYTES];
        if (mode.equals("chase")) {
            // Sattolo's shuffle creates a single cycle, so every element is visited.
            for (int i = 0; i < data.length; i++) data[i] = i;
            Random random = new Random(42);
            for (int i = data.length - 1; i > 0; i--) {
                int j = random.nextInt(i);
                int value = data[i]; data[i] = data[j]; data[j] = value;
            }
        } else {
            Random random = new Random(42);
            for (int i = 0; i < data.length; i++) data[i] = random.nextInt();
        }
    }

    private long allocationBatch() {
        long sum = 0;
        for (int i = 0; i < OPS_PER_BATCH; i++) {
            byte[] bytes = new byte[256];
            bytes[0] = (byte) sequence++;
            escaped = bytes; // Deliberate escape prevents scalar replacement.
            sum += bytes[0];
        }
        return sum;
    }

    private long branchBatch() {
        long sum = sequence;
        for (int i = 0; i < OPS_PER_BATCH; i++) {
            int value = data[cursor++];
            if (cursor == data.length) cursor = 0;
            // The JIT may if-convert this: branch misses must be measured, not assumed.
            if (value < 0) sum = Long.rotateLeft(sum, 3) ^ value;
            else sum = Long.rotateRight(sum, 5) + value;
        }
        sequence = sum;
        return sum;
    }

    private long streamBatch() {
        long sum = 0;
        for (int i = 0; i < OPS_PER_BATCH; i++) {
            sum += data[cursor++];
            if (cursor == data.length) cursor = 0;
        }
        return sum;
    }

    private long chaseBatch() {
        for (int i = 0; i < OPS_PER_BATCH; i++) cursor = data[cursor];
        return cursor;
    }

    private long lockBatch() {
        long sum = sequence;
        for (int i = 0; i < OPS_PER_BATCH; i++) {
            synchronized (monitor) {
                sum += (i ^ sequence++);
            }
        }
        return sum;
    }

    private long parkBatch() {
        long sum = sequence;
        for (int i = 0; i < OPS_PER_BATCH; i++) {
            LockSupport.parkNanos(100L);
            sum += i ^ sequence++;
        }
        return sum;
    }

    private long run(String mode, int batches) {
        long result = 0;
        for (int i = 0; i < batches; i++) {
            result += switch (mode) {
                case "allocation" -> allocationBatch();
                case "branch" -> branchBatch();
                case "stream" -> streamBatch();
                case "chase" -> chaseBatch();
                case "lock" -> lockBatch();
                case "park" -> parkBatch();
                default -> throw new AssertionError(mode);
            };
        }
        sink = result;
        return result;
    }

    public static void main(String[] args) {
        if (args.length == 1 && args[0].equals("--help")) {
            System.out.println("Usage: java VendorWorkload.java MODE BATCHES WARMUP_BATCHES WORKING_SET_MIB");
            System.out.println("MODE: allocation|branch|stream|chase|lock|park; batches 1-1000000; warmup 0-1000000; MiB 1-256");
            System.out.println("Synthetic fixed-work fixture. Use an external timeout; prints measurement uptime bounds.");
            return;
        }
        try {
            if (args.length != 4) throw new IllegalArgumentException("expected four arguments; use --help");
            String mode = args[0];
            if (!mode.matches("allocation|branch|stream|chase|lock|park")) throw new IllegalArgumentException("invalid mode");
            int batches = number(args[1], 1, 1_000_000, "batches");
            int warmup = number(args[2], 0, 1_000_000, "warmup batches");
            int mib = number(args[3], 1, 256, "working set MiB");
            VendorWorkload workload = new VendorWorkload(mode, mib);
            var runtime = ManagementFactory.getRuntimeMXBean();
            System.out.printf("fixture=synthetic%nmode=%s%njdk=%s%nworking_set_mib=%d%n",
                    mode, Runtime.version(), mib);
            workload.run(mode, warmup);
            long uptimeStart = runtime.getUptime();
            long start = System.nanoTime();
            long checksum = workload.run(mode, batches);
            long elapsed = System.nanoTime() - start;
            long uptimeEnd = runtime.getUptime();
            long operations = (long) batches * OPS_PER_BATCH;
            System.out.printf(Locale.ROOT,
                    "warmup_batches=%d%nmeasured_operations=%d%nmeasurement_start_uptime_ms=%d%n"
                    + "measurement_end_uptime_ms=%d%nelapsed_ns=%d%noperations_per_second=%.3f%nchecksum=%d%n",
                    warmup, operations, uptimeStart, uptimeEnd, elapsed, operations * 1e9 / elapsed, checksum);
        } catch (IllegalArgumentException ex) {
            System.err.println(ex.getMessage());
            System.exit(2);
        }
    }

    private static int number(String value, int min, int max, String name) {
        try {
            int parsed = Integer.parseInt(value);
            if (parsed >= min && parsed <= max) return parsed;
        } catch (NumberFormatException ignored) {
            // Report the same bounded input contract for malformed and out-of-range values.
        }
        throw new IllegalArgumentException(name + " must be " + min + "-" + max);
    }
}
