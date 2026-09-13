# Evidence log template

Keep one entry per experiment. Store beside the artifacts; redact before sharing.

```text
id:                 EXP-<n>
date_utc:
objective:          <metric, percentile, load, environment>
workload_class:     fixed-rate | max-sustainable | batch | startup | footprint
hypothesis:         <one cause, stated so it can be rejected>
prediction:         <what the evidence shows if the hypothesis is true / false>
host:               <readiness report path; CPU, kernel, topology>
jdk:                <java -version; collector; final JVM flags>
app_revision:       <commit, dirty flag>
load:               <generator, rate schedule, duration, warmup, repetitions>
control:            <unchanged configuration and its results>
change:             <exactly one factor>
artifacts:          <paths to JFR, logs, histograms, perf data, JSON>
result:             <distributions with variance, not a single mean>
interference:       <GC, JIT, OS, co-tenants, thermal notes>
decision:           confirmed | rejected | inconclusive — and next step
rollback:           <how the change is undone; verified?>
```

A result is inconclusive when symbol resolution failed, the load generator
saturated, runs disagree beyond their variance, or the control drifted.
