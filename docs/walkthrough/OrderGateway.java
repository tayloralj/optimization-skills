import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.locks.LockSupport;

/**
 * Demo "order gateway" for the walkthrough. It replays a fixed-rate (open-loop) arrival
 * schedule on one thread, handles each order, and records intended start, actual start,
 * and end time per order, so response time includes any queueing behind a stall.
 *
 *   javac -d build OrderGateway.java
 *   java -Xms64m -Xmx64m -Xlog:gc*,safepoint:file=gc.log:time,uptime,level,tags \
 *        -cp build OrderGateway allocating 20 10000 before.csv
 *
 * Modes:
 *   allocating  builds a String record per order and keeps recent orders in a boxed map
 *   zero-alloc  encodes into a reused byte buffer and keeps recent orders in primitive arrays
 */
public final class OrderGateway {
    static final int RECENT = 200_000;

    /** Handler with the typical garbage: string building, boxing, a map of recent orders. */
    public static final class AllocatingHandler implements Runnable {
        private final Map<Long, String> recent = new LinkedHashMap<>(RECENT * 2) {
            @Override
            protected boolean removeEldestEntry(Map.Entry<Long, String> eldest) {
                return size() > RECENT;
            }
        };
        private long nextId;
        long checksum;

        @Override
        public void run() {
            long id = ++nextId;
            long price = 10_000 + (id % 500);
            int quantity = (int) (1 + id % 100);
            String record = "order=" + id + ",price=" + price + ",qty=" + quantity + ",side=" + (id % 2 == 0 ? "BUY" : "SELL");
            recent.put(id, record);
            checksum += record.length();
        }
    }

    /** Alternative representation: binary encoding and primitive retention; not a drop-in map/string API. */
    public static final class ZeroAllocHandler implements Runnable {
        private final byte[] buffer = new byte[32];
        private final long[] recentIds = new long[RECENT];
        private final long[] recentPrices = new long[RECENT];
        private final int[] recentQuantities = new int[RECENT];
        private long nextId;
        long checksum;

        @Override
        public void run() {
            long id = ++nextId;
            long price = 10_000 + (id % 500);
            int quantity = (int) (1 + id % 100);
            putLong(buffer, 0, id);
            putLong(buffer, 8, price);
            putInt(buffer, 16, quantity);
            buffer[20] = (byte) (id % 2 == 0 ? 'B' : 'S');
            int slot = (int) (id % RECENT);
            recentIds[slot] = id;
            recentPrices[slot] = price;
            recentQuantities[slot] = quantity;
            checksum += buffer[20];
        }

        private static void putLong(byte[] b, int offset, long v) {
            for (int i = 0; i < 8; i++) {
                b[offset + i] = (byte) (v >>> (8 * i));
            }
        }

        private static void putInt(byte[] b, int offset, int v) {
            for (int i = 0; i < 4; i++) {
                b[offset + i] = (byte) (v >>> (8 * i));
            }
        }
    }

    public static void main(String[] args) throws IOException {
        if (args.length != 4) {
            System.err.println("Usage: OrderGateway allocating|zero-alloc SECONDS RATE_PER_SECOND OUTPUT.csv");
            System.exit(2);
        }
        Runnable handler = switch (args[0]) {
            case "allocating" -> new AllocatingHandler();
            case "zero-alloc" -> new ZeroAllocHandler();
            default -> throw new IllegalArgumentException("mode must be allocating or zero-alloc");
        };
        int seconds = Integer.parseInt(args[1]);
        int rate = Integer.parseInt(args[2]);
        Path output = Path.of(args[3]);

        // Warm up untimed so JIT compilation is not part of the measurement.
        for (int i = 0; i < 2_000_000; i++) {
            handler.run();
        }

        long total = (long) seconds * rate;
        long intervalNanos = 1_000_000_000L / rate;
        long[] intended = new long[(int) total];
        long[] started = new long[(int) total];
        long[] ended = new long[(int) total];
        long origin = System.nanoTime() + 50_000_000L;
        for (int i = 0; i < total; i++) {
            long due = origin + i * intervalNanos;
            long now = System.nanoTime();
            while (now < due) {
                long wait = due - now;
                if (wait > 200_000) {
                    LockSupport.parkNanos(wait - 100_000);
                } else {
                    Thread.onSpinWait();
                }
                now = System.nanoTime();
            }
            intended[i] = due;
            started[i] = now;
            handler.run();
            ended[i] = System.nanoTime();
        }

        try (BufferedWriter out = Files.newBufferedWriter(output)) {
            out.write("intended_start_ns,actual_start_ns,end_ns\n");
            for (int i = 0; i < total; i++) {
                out.write(intended[i] + "," + started[i] + "," + ended[i] + "\n");
            }
        }
        System.out.printf("mode=%s orders=%d rate=%d/s csv=%s%n", args[0], total, rate, output);
    }
}
