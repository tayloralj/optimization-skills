# Bundle format (bundle_format=1)

`jvmcap-<host or host-HASH>-<pid>-<UTC timestamp>.tar.gz` contains one directory.
With `--split-mb` it arrives as `NAME.tar.gz.part-000`, `-001`, ... (rejoin with
`cat` in order). With `--digest` a text copy of `DIGEST.txt` sits next to it as
`NAME.digest.txt`.

```text
MANIFEST.txt            key=value metadata and step results (see below)
SHA256SUMS              sha256 of every other file
commands.log            every command run, with UTC timestamps
DIGEST.txt              text summary (only with --digest)
proc-start/, proc-end/  /proc and cgroup snapshots at window start and end:
  threads.tsv           tid, comm, utime, stime (clock ticks), voluntary/nonvoluntary
                        context switches, run_delay_ns (schedstat), last processor,
                        state (R/S/D/T...), wchan (kernel wait channel)
  interrupts softirqs vmstat meminfo stat loadavg diskstats
  net_snmp net_netstat pressure_{cpu,io,memory} uptime_s timestamp
  pid_status pid_stat pid_io pid_schedstat pid_limits pid_cgroup pid_smaps_rollup
  cgroup_{cpu.stat,cpu.max,cpu.pressure,memory.current,memory.max,memory.high,
          memory.events,memory.pressure,io.pressure}   (cgroup v2, when readable)
samples/host.tsv        every --sample-interval seconds: host uptime, host CPU jiffies
                        (user nice system idle iowait irq softirq steal), process
                        utime/stime, rss_kb, host pressure totals (us), cgroup
                        nr_throttled and throttled_usec
samples/threads.tsv     uptime_s, tid, comm, cpu_ticks: a row only when a thread's CPU
                        time changed since its previous row (the first sample lists all)
host/readiness.txt      profiling-readiness report (no smoke tests unless requested)
host/audit.txt          latency-host-audit output with finding= lines
jvm/VM.version.txt ...  jcmd VM.version, VM.uptime, VM.flags, GC.heap_info (start and end),
                        VM.metaspace, Compiler.codecache, VM.log list
jvm/nmt-start/, nmt-end/ native-memory-snapshot.sh output (only when NMT is enabled)
jvm/recording.jfr       new recording of the window (sensitive events off, scrubbed), or
jvm/continuous.jfr      dump of an existing continuous recording (scrubbed)
jvm/asprof-EVENT.jfr    async-profiler recording (optional; .collapsed when no jfr tool)
jvm/thread-dump-NN.txt  jcmd Thread.print -l (optional)
jvm/thread-dump-NN.json jcmd Thread.dump_to_file -format=json (optional, includes virtual threads)
jvm/class-histogram-{start,end}.txt  jcmd GC.class_histogram -all (optional)
logs/NN-<name>          GC log files named by the JVM's log configuration (or its
                        command line when jcmd is unavailable), newest first
vendor/<artifact>       optional copied VTune, uProf, perf, or PCM file/directory
```

Times in `uptime_s`, the samples, and the analysis are host uptime seconds.
The JVM started at `target_start_ticks / clk_tck` on that clock, which maps
GC log `uptime` decorations to host time without `jcmd`.

## Manifest keys

| Key | Meaning |
| --- | --- |
| `bundle_format`, `kit_version` | Format and collector versions |
| `host`, `kernel`, `arch`, `logical_cpus`, `clk_tck` | Host identity (hashed with `--redact-hostname`), clock ticks per second |
| `pid`, `target_start_ticks` | Target and its start time, to detect PID reuse and align clocks |
| `target_mount_ns` | `same`, or `different` when collected from a debug container or the node |
| `duration_s`, `started_utc`, `finished_utc` | Requested window and wall-clock bounds |
| `start_at`, `triggers`, `trigger_fired`, `waited_s` | Unattended start settings, what started the window (`immediate` if nothing), and the wait |
| `jfr_mode`, `jfr_settings`, `thread_dumps`, `json_thread_dumps`, `class_histogram`, `gc_logs`, `asprof_event`, `sample_interval_s`, `max_mb` | Options used |
| `redact_hostname`, `keep_command_line`, `digest`, `split_mb` | Privacy and transfer options |
| `jcmd`, `jcmd_source`, `jcmd_timeout_s`, `jfr_tool` | Attach path (`jdk`, `jdk-other-namespace`, `async-profiler`, `none`), timeout, and tools used |
| `jvm_unresponsive` | `1` when the JVM did not answer `VM.version`; later JVM steps were skipped |
| `step.<name>` | `ok`, `failed(...)`, `timeout(Ns)`, `skipped(reason)`, or a count such as `copied=N`, `rows=N`, `bytes=N` |
| `jfr_scrub.<file>` | `ok`, `source-disabled(...)`, `skipped(--keep-command-line)`, `NOT_SCRUBBED(...)`, or `failed(...)` |
| `gc_log_skipped.<file>` | A GC log left out to stay within budget |
| `content_bytes`, `size_warning` | Size before archiving; warning when over `--max-mb` |
| `interrupted`, `target_alive_at_end` | Whether the run was cut short or the JVM exited |
| `vendor_artifacts` | Number of operator-supplied artifacts requested for `vendor/` |

## Loose files

`analyze-bundle.py DIR OUT` on a directory without a manifest builds
`jvmcap-loose-<dir>/` with the same layout (`jvm/`, `logs/`, `crash/`,
`other/`), classifying each regular file by content, and writes
`source=loose-files` plus one `loose_file.N=<path> -> <kind>` key per file.
Symbolic links are ignored. There are no checksums to verify.

## Analysis output

`ANALYSIS.md` for people and `analysis.json` (`analysis_format=1`) for agents
and `compare-bundles.py`. Top-level JSON keys include `capture`, `process`,
`threads`, `thread_groups_cpu_pct`, `hot_thread_stacks`, `timeseries`, `host`,
`cgroup`, `gc`, `profiles`, `collapsed_profiles`, `nmt`,
`class_histogram_growth`, `thread_dumps`, `stuck_threads`, `crashes`,
`jvm_version`, `findings`, and `next_skills`; sections without evidence are
omitted.

## Compatibility

- Additive changes (new files, new keys, new trailing TSV columns) keep
  `bundle_format=1`; the analyser ignores unknown files and keys and reads TSV
  columns by header name.
- Breaking layout changes bump `bundle_format`; the analyser rejects formats it
  does not know (exit 7).
