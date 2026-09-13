/** Synthetic fixture: allocation recurs every four million calls, beyond warmup. */
public final class Periodic implements Runnable {
    private static volatile Object sink;
    private long calls;
    public void run() {
        if (++calls % 4_000_000 < 1_000_000) sink = new byte[128];
    }
}
