Synthetic scenario: Intel pcm-memory reports 45 GB/s on a shared Xeon socket
while our Java service and a backup job run. Someone says all 45 GB/s belongs
to the Java process, proves its HashMap is the bottleneck, and suggests using
the same PCM event codes on AMD Ryzen. Can we accept that? Plan a better test.
