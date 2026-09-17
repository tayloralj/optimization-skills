# Evidence log template

Keep one entry per experiment. Store beside the artifacts; redact before sharing.

```text
id:                 EXP-<n>
date_utc:
objective:          <metric, percentile, load, environment>
workload_class:     fixed-rate | max-sustainable | batch | startup | footprint | recovery-episode
hypothesis:         <one cause, stated so it can be rejected>
prediction:         <what the evidence shows if the hypothesis is true / false>
host:               <readiness report path; CPU, kernel, topology>
jdk:                <java -version; collector; final JVM flags>
app_revision:       <commit, dirty flag>
load:               <generator, rate schedule, fault schedule and seed, duration, warmup, repetitions>
completeness:       <operations completed / offered, per run; any shortfall makes the result invalid>
control:            <unchanged configuration and its results>
change:             <exactly one factor>
artifacts:          <paths to JFR, logs, histograms, perf data, JSON>
result:             <distributions with variance, not a single mean>
interference:       <GC, JIT, OS, co-tenants, thermal notes>
decision:           confirmed | rejected | inconclusive — and next step
rollback:           <how the change is undone; verified?>
reproduce:          <command run from the stored evidence directory, and when it was last re-run>
```

Store everything the reproduce command needs (configs, probes, summarisers)
beside the results, and re-run it from there before publishing. A prototype
applied by patching source must fail loudly when its anchor no longer matches,
and the evidence should say which revision it was measured against.

A result is inconclusive when symbol resolution failed, the load generator
saturated, runs disagree beyond their variance, or the control drifted. It is
invalid when fewer operations completed than were offered.
