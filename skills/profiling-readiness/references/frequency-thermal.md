# Frequency, power, and thermal evidence

Run `scripts/frequency-thermal-snapshot.py` before comparing Intel and AMD
profiles or latency measurements. It reads cpufreq policy, per-CPU frequency,
EPP/governor, boost state, thermal zones, and Linux powercap energy counters
without changing the host. Set `HOST_ROOT` or `--root` only for offline or test
filesystems.

```bash
python3 skills/profiling-readiness/scripts/frequency-thermal-snapshot.py \
  > "$evidence/frequency-thermal.json"
```

`scaling_cur_freq` is a policy/current reading rather than a precise average of
retired instructions; APERF/MPERF or a vendor profiler's frequency analysis is
stronger when available. Energy counters are package or domain scope and
include other processes. Missing fields are unknown, not zero.

Keep governor, EPP, boost policy, CPU placement, SMT load, and thermal state
consistent across baseline and candidate runs. Record APERF/MPERF, RAPL, or AMD
energy readings with their units and interval when collecting them through
`perf`, VTune, uProf, or PCM. A faster result with a higher average frequency
is not evidence of a code improvement until frequency is controlled or
accounted for. Never change governors, boost, power limits, MSRs, or thermal
configuration automatically from a profiling skill.
