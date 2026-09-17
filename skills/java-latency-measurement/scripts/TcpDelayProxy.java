import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.LockSupport;

/**
 * Userspace TCP delay proxy: adds a fixed one-way delay in each direction, so round-trip
 * time grows by twice the delay. For lab experiments that need a realistic RTT when
 * `tc netem` (root) is not available. No dependencies; run with the JDK source launcher:
 *
 *   java scripts/TcpDelayProxy.java --target 127.0.0.1:9000 --delay-ms 0.5 --duration 600
 *
 * The first stdout line is "listening HOST:PORT"; point the client there. It binds to
 * loopback unless --listen names another address and --allow-non-loopback is given.
 * It adds delay only: no loss, reordering, or bandwidth limit, and the added delay has
 * scheduler jitter (tens of microseconds on an untuned host). Measure the achieved RTT
 * rather than assuming the requested value. Each direction buffers at most
 * --max-queue chunks, so a slow reader applies backpressure instead of growing memory.
 */
public final class TcpDelayProxy {
    private static final byte[] EOF = new byte[0];

    private record Chunk(long dueNanos, byte[] bytes) {
    }

    public static void main(String[] args) throws Exception {
        String listen = "127.0.0.1:0";
        String target = null;
        double delayMs = -1;
        long durationS = 600;
        int maxQueue = 4096;
        boolean allowNonLoopback = false;
        for (int i = 0; i < args.length; i++) {
            String arg = args[i];
            String value = i + 1 < args.length ? args[i + 1] : null;
            switch (arg) {
                case "--listen" -> { listen = require(arg, value); i++; }
                case "--target" -> { target = require(arg, value); i++; }
                case "--delay-ms" -> { delayMs = Double.parseDouble(require(arg, value)); i++; }
                case "--duration" -> { durationS = Long.parseLong(require(arg, value)); i++; }
                case "--max-queue" -> { maxQueue = Integer.parseInt(require(arg, value)); i++; }
                case "--allow-non-loopback" -> allowNonLoopback = true;
                case "-h", "--help" -> { usage(); return; }
                default -> fail("unknown argument: " + arg);
            }
        }
        if (target == null) fail("--target HOST:PORT is required");
        if (delayMs < 0 || delayMs > 10_000 || Double.isNaN(delayMs)) fail("--delay-ms must be between 0 and 10000");
        if (durationS < 1 || durationS > 86_400) fail("--duration must be between 1 and 86400 seconds");
        if (maxQueue < 1 || maxQueue > 1_000_000) fail("--max-queue must be between 1 and 1000000");
        InetSocketAddress listenAddress = parse(listen);
        InetSocketAddress targetAddress = parse(target);
        if (!listenAddress.getAddress().isLoopbackAddress() && !allowNonLoopback) {
            fail("refusing to listen on non-loopback " + listen + " without --allow-non-loopback");
        }
        long delayNanos = Math.round(delayMs * 1_000_000);
        AtomicLong forwarded = new AtomicLong();
        AtomicLong connections = new AtomicLong();

        ServerSocket server = new ServerSocket();
        server.bind(listenAddress, 50);
        System.out.printf(Locale.ROOT, "listening %s:%d target=%s delay_ms_each_way=%.3f%n",
            server.getInetAddress().getHostAddress(), server.getLocalPort(), target, delayMs);
        System.out.flush();

        final int queueLimit = maxQueue;
        Thread acceptor = new Thread(() -> {
            while (!server.isClosed()) {
                try {
                    Socket client = server.accept();
                    Socket upstream = new Socket();
                    upstream.connect(targetAddress, 5_000);
                    client.setTcpNoDelay(true);
                    upstream.setTcpNoDelay(true);
                    connections.incrementAndGet();
                    pipe(client, upstream, delayNanos, queueLimit, forwarded);
                    pipe(upstream, client, delayNanos, queueLimit, forwarded);
                } catch (IOException e) {
                    if (!server.isClosed()) {
                        System.err.println("connection failed: " + e);
                    }
                }
            }
        }, "delay-proxy-accept");
        acceptor.setDaemon(true);
        acceptor.start();

        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(durationS);
        while (System.nanoTime() < deadline) {
            LockSupport.parkNanos(Math.min(deadline - System.nanoTime(), 200_000_000L));
        }
        server.close();
        System.out.printf(Locale.ROOT, "stopped connections=%d bytes_forwarded=%d%n", connections.get(), forwarded.get());
    }

    private static void pipe(Socket from, Socket to, long delayNanos, int maxQueue, AtomicLong forwarded) {
        BlockingQueue<Chunk> queue = new ArrayBlockingQueue<>(maxQueue);
        Thread reader = new Thread(() -> {
            byte[] buf = new byte[1 << 16];
            try (InputStream in = from.getInputStream()) {
                int n;
                while ((n = in.read(buf)) > 0) {
                    queue.put(new Chunk(System.nanoTime() + delayNanos, Arrays.copyOf(buf, n)));
                }
            } catch (IOException | InterruptedException ignored) {
                // Peer closed or proxy stopping; the writer closes both sockets.
            }
            try {
                queue.put(new Chunk(System.nanoTime() + delayNanos, EOF));
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
        }, "delay-proxy-read");
        Thread writer = new Thread(() -> {
            try (OutputStream out = to.getOutputStream()) {
                while (true) {
                    Chunk chunk = queue.take();
                    long wait;
                    while ((wait = chunk.dueNanos() - System.nanoTime()) > 0) {
                        LockSupport.parkNanos(wait);
                    }
                    if (chunk.bytes() == EOF) {
                        break;
                    }
                    out.write(chunk.bytes());
                    forwarded.addAndGet(chunk.bytes().length);
                }
            } catch (IOException | InterruptedException ignored) {
                // Peer closed; fall through to close both ends.
            }
            closeQuietly(from);
            closeQuietly(to);
        }, "delay-proxy-write");
        reader.setDaemon(true);
        writer.setDaemon(true);
        reader.start();
        writer.start();
    }

    private static InetSocketAddress parse(String hostPort) {
        int colon = hostPort.lastIndexOf(':');
        if (colon <= 0 || colon == hostPort.length() - 1) fail("expected HOST:PORT, got " + hostPort);
        String host = hostPort.substring(0, colon);
        if (host.startsWith("[") && host.endsWith("]")) host = host.substring(1, host.length() - 1);
        int port;
        try {
            port = Integer.parseInt(hostPort.substring(colon + 1));
        } catch (NumberFormatException e) {
            fail("invalid port in " + hostPort);
            return null;
        }
        if (port < 0 || port > 65535) fail("invalid port in " + hostPort);
        try {
            return new InetSocketAddress(InetAddress.getByName(host), port);
        } catch (IOException e) {
            fail("cannot resolve " + host);
            return null;
        }
    }

    private static void closeQuietly(Socket socket) {
        try {
            socket.close();
        } catch (IOException ignored) {
            // Already closed.
        }
    }

    private static String require(String arg, String value) {
        if (value == null) fail(arg + " needs a value");
        return value;
    }

    private static void usage() {
        System.out.println("usage: java TcpDelayProxy.java --target HOST:PORT --delay-ms MS [--listen HOST:PORT]"
            + " [--duration SECONDS] [--max-queue CHUNKS] [--allow-non-loopback]");
    }

    private static void fail(String message) {
        System.err.println("TcpDelayProxy: " + message);
        System.exit(2);
    }
}
