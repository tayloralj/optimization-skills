// Allocation-free hot path used to test AllocationProbe: encodes into a reused buffer.
public final class NoAlloc implements Runnable {
    private final byte[] buffer = new byte[64];
    private long sequence;

    @Override
    public void run() {
        long value = ++sequence;
        for (int i = 0; i < 8; i++) {
            buffer[i] = (byte) (value >>> (i * 8));
        }
    }
}
