// Allocating hot path used to test AllocationProbe: builds a String per call.
public final class Allocates implements Runnable {
    private long sequence;
    private int sink;

    @Override
    public void run() {
        sink += Long.toString(++sequence).length();
    }
}
