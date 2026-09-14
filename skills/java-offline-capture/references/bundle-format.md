# Bundle format (bundle_format=1)

`jvmcap-<host or host-HASH>-<pid>-<UTC timestamp>.tar.gz` contains one directory:

```text
MANIFEST.txt            key=value metadata and step results (see below)
SHA256SUMS              sha256 of every other file
commands.log            every command run, with UTC timestamps
proc-start/, proc-end/  /proc snapshots at window start and end:
  threads.tsv           tid, comm, utime, stime (clock ticks), voluntary/nonvoluntary
                        context switches, run_delay_ns (schedstat), last processor
  interrupts softirqs vmstat meminfo stat loadavg diskstats
  net_snmp net_netstat pressure_{cpu,io,memory} uptime_s timestamp
  pid_status pid_limits pid_cgroup pid_smaps_rollup
host/readiness.txt      profiling-readiness report (no smoke tests unless requested)
host/audit.txt          latency-host-audit output with finding= lines
jvm/VM.version.txt ...  jcmd VM.version, VM.uptime, VM.flags, GC.heap_info (start and end),
                        VM.metaspace, Compiler.codecache, VM.log list
jvm/nmt-start/, nmt-end/ native-memory-snapshot.sh output (only when NMT is enabled)
jvm/recording.jfr       new recording of the window (scrubbed), or
jvm/continuous.jfr      dump of an existing continuous recording (scrubbed)
jvm/asprof-EVENT.jfr    async-profiler recording (optional)
jvm/thread-dump-NN.txt  jcmd Thread.print -l (optional)
logs/NN-<name>          GC log files named by the JVM's log configuration, newest first
```

## Manifest keys

| Key | Meaning |
| --- | --- |
| `bundle_format`, `kit_version` | Format and collector versions |
| `host`, `kernel`, `logical_cpus`, `clk_tck` | Host identity (hashed with `--redact-hostname`), clock ticks per second |
| `pid`, `target_start_ticks` | Target and its start time, to detect PID reuse |
| `duration_s`, `started_utc`, `finished_utc` | Requested window and wall-clock bounds |
| `jfr_mode`, `jfr_settings`, `thread_dumps`, `gc_logs`, `asprof_event`, `max_mb` | Options used |
| `redact_hostname`, `keep_command_line` | Privacy options |
| `jcmd`, `jfr_tool` | Tool paths used, or `missing` |
| `step.<name>` | `ok`, `failed(rc=N)`, or `skipped(reason)` for each step |
| `jfr_scrub.<file>` | `ok`, `skipped(--keep-command-line)`, `NOT_SCRUBBED(...)`, or `failed(...)` |
| `content_bytes`, `size_warning` | Size before archiving |
| `interrupted`, `target_alive_at_end` | Whether the run was cut short or the JVM exited |

## Compatibility

- Additive changes (new files, new keys) keep `bundle_format=1`; the analyser
  ignores unknown files and keys.
- Breaking layout changes bump `bundle_format`; the analyser should reject
  formats it does not know.
