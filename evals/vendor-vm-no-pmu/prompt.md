Synthetic scenario: a KVM guest reports GenuineIntel / SierraForest, two vCPUs,
and perf_event_paranoid=4. Its event sources are breakpoint, kprobe, msr,
software, tracepoint, and uprobe; there is no cpu or uncore PMU. Java and VTune
are not installed. Will lowering perf_event_paranoid make Intel PCM report host
memory-channel bandwidth? Plan validation without changing either host or guest.
