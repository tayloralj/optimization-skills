// Synthetic target for the offline capture tests: a contended monitor, allocation
// churn, a parked virtual thread, and a child process started every second whose
// command line carries a fake secret that must never reach a bundle.
import java.util.*;
public class CaptureTarget {
  static final Object LOCK = new Object();
  public static void main(String[] a) throws Exception {
    long seconds = a.length > 0 ? Long.parseLong(a[0]) : 60;
    for (int t = 0; t < 2; t++) {
      Thread worker = new Thread(() -> { while (true) synchronized (LOCK) { burn(100_000); } }, "contender-" + t);
      worker.setDaemon(true);
      worker.start();
    }
    Thread.ofVirtual().name("parked-virtual").start(() -> { try { Thread.sleep(seconds * 1000); } catch (InterruptedException e) { } });
    Thread spawner = new Thread(() -> {
      try {
        while (true) { new ProcessBuilder("true", "--password=fixture-secret-7Q").start().waitFor(); Thread.sleep(1000); }
      } catch (Exception e) { }
    }, "spawner");
    spawner.setDaemon(true);
    spawner.start();
    List<byte[]> keep = new ArrayList<>();
    long end = System.nanoTime() + seconds * 1_000_000_000L;
    while (System.nanoTime() < end) {
      keep.add(new byte[32 * 1024]);
      if (keep.size() > 400) keep.clear();
      burn(5_000);
    }
  }
  static long burn(int n) { long x = 0; for (int i = 0; i < n; i++) x += Integer.toString(i).hashCode(); return x; }
}
