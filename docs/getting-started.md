# Getting started

## What this is, in one paragraph

These are instructions and small tools that an AI coding agent (Claude Code or
OpenAI Codex) loads when you ask it about Java performance. They guide the agent to
check what the machine can measure, collect evidence, change one thing, and
verify the result. You describe the problem; the agent can run available tools.
Behavioral validation status is recorded in [compatibility](compatibility.md).

## Who it is for

- Java developers and SREs running JVM services or batch jobs **on Linux**.
- Especially latency-sensitive systems (trading, messaging, real-time
  pipelines), but most of it applies to ordinary web services.
- No prior profiling experience needed. Root access helps for some steps
  but is never required to get started.

Not a fit: macOS or Windows hosts (the host scripts read Linux `/proc` and
`/sys`), non-JVM languages, or front-end performance.

## Install (two minutes)

The GitHub repository is private for now, so you need read access and a working
`git` login (for example an SSH key).

Claude Code:

```bash
claude plugin marketplace add git@github.com:tayloralj/optimization-skills.git
claude plugin install optimization-skills@optimization-skills
```

Codex (or Claude Code without the plugin system):

```bash
git clone git@github.com:tayloralj/optimization-skills.git
cd optimization-skills && ./install.sh
```

Restart the agent afterwards.

To update later, run `claude plugin marketplace update optimization-skills`
and `claude plugin update optimization-skills@optimization-skills` for the
plugin, or `git pull` and re-run `./install.sh` (with the same options) in the
checkout. Restart the agent, then rebuild any offline collector kits you hand
out. See [Update to the latest version](../README.md#update-to-the-latest-version).

## Your first conversation

Ask in your own words. For an unexplained symptom, start with
`java-performance-investigation`: it identifies the affected service and time
window, chooses online or offline evidence, and selects the next specialist.
You do not need to choose between two triage skills; `linux-jvm-debug` supplies
supporting helpers within this workflow. A specific profiler request or supplied
artifact can go directly to its specialist.

Good first prompts:

| You say | What happens |
| --- | --- |
| "My Spring service's p99 latency jumps every few minutes. Help me find out why." | The **investigation** skill agrees a target and plan, then usually checks measurement validity and GC first |
| "Here are our GC logs (`gc.log*`). Are pauses a problem?" | The **GC** skill summarises pauses, time-to-safepoint, and alarms, and explains them |
| "This JVM's memory keeps growing but the heap looks fine." | The **native memory** skill takes two snapshots and builds a memory ledger |
| "Is this benchmark trustworthy?" (pointing at a JMH class) | The **JMH** skill checks it still models production code and runs it properly |
| "Review this order-handling hot path for latency problems." | The **low-latency patterns** skill looks for allocation, contention, and blocking, and proves fixes |
| "Is this box ready for latency testing? Hot threads will run on CPUs 4-7." | The **low-latency tuning** skill audits the host and lists what would interfere |

Name a skill with `/optimization-skills:java-gc-tuning ...` for the Claude
plugin, `/java-gc-tuning ...` for standalone Claude skills, or
`$java-gc-tuning ...` in Codex.

When a profiling example uses a value such as `PID 12345`, that value is only a
placeholder. Instruct the agent to discover the real JVM first; it must verify
the selected process owner and start time before attaching.

## What the agent will and won't do

It **will** read logs and `/proc`, run short read-only checks, start bounded
recordings of your own processes, run benchmarks, and propose code changes.

It **won't**, unless you explicitly ask and approve:

- change kernel settings, CPU governors, or IRQ routing;
- restart services or change JVM flags on production;
- run anything with `sudo`: when root is needed it prints the command for
  you (in Claude Code, run it with `! sudo ...`);
- publish profiles, which can contain class names, hosts, and data.

The caution is deliberate. Profilers and kernel tweaks can slow down or
destabilise a live system, and performance numbers are easy to get wrong in
ways that look convincing. If you want the agent to make reversible changes on
a benchmark machine, say that the host is a lab host and it will use
**lab mode** (see the `linux-low-latency-tuning` skill).

## No root? Start here

Many machines block `perf` and eBPF by default (Ubuntu does). You can still do
most investigations:

1. **JDK Flight Recorder**, built into the JDK: GC, locks, I/O, allocation, CPU samples.
   Ask: "Record this JVM with JFR for two minutes and tell me what stands out."
2. **GC and safepoint logs**: add
   `-Xlog:gc*,safepoint:file=gc.log:time,uptime,level,tags` and ask for a summary.
3. **`jcmd`** diagnostics and Native Memory Tracking for memory questions.
4. **The host audit**, which only reads files.
5. **Correct latency measurement** with intended start times and the latency report.

Only CPU hardware counters, `perf`, eBPF, and lab-mode tuning need more
access, and the readiness check tells you exactly which.

## The problem host can't run an agent

Production and QA hosts usually won't have Codex or Claude installed, and you
may not have a shell there at all. Ask for a capture kit instead:

> "Build a collector kit for our order service on prod (PID unknown, runs as
> `orders`) to capture the 18:00 latency spike. I'll send the bundle back."

The **`java-offline-capture`** skill builds `jvm-collector-VERSION.tar.gz` and
writes step-by-step instructions for the operator: verify, `--check`,
`--dry-run`, run as the application user, and copy the bundle back. The
collector needs only bash and coreutils on the host. It is read-only apart
from attaching to that one JVM, and it keeps environment variables and command
lines out of recordings.

Nobody has to be awake at 18:00: the collector can wait for a time
(`--start-at 17:55`) or a condition (`--trigger cpu:350`, `gcpause:200`,
`rss:4000`, or a flag file) and capture then. It also copes with awkward
hosts: JRE-only runtimes (bundle async-profiler into the kit), distroless
Kubernetes pods (run it from a debug container), hung JVMs (diagnostics time
out and `/proc` evidence is still collected), and channels that only take
small files or text (`--split-mb`, `--digest`, or a single-file kit pasted
into a console).

When the bundle comes back, the agent verifies it and produces `ANALYSIS.md`
with findings, hot threads matched to their stacks, and a time series of the
busiest moments, then carries on with the usual skills. It can also analyse a
folder of files you already have (JFR recordings, GC logs, jstack output,
`hs_err` crash logs), and compare an incident capture with a healthy baseline.

## See it end to end

The [walkthrough](walkthrough/README.md) takes a p99.99 latency problem from
symptom to a repeated comparison, with separate diagnostic captures and
explicit limits on tail-percentile conclusions. [Examples](examples.md) shows real output from every tool and how to
read it.

## Glossary

| Term | Meaning |
| --- | --- |
| **p99 / p99.99** | The latency that 99% / 99.99% of operations beat. Tail percentiles show the rare slow cases averages hide |
| **Open-loop / fixed-rate load** | Requests arrive on a schedule whether or not earlier ones finished, like real users |
| **Coordinated omission** | A measurement error: timing only from when a request actually started hides the time it waited behind a stall |
| **GC pause** | Time the JVM stops application threads to reclaim memory |
| **Safepoint / time-to-safepoint (TTSP)** | A point where all Java threads stop for JVM work; TTSP is how long it takes them to stop |
| **JIT / deoptimization** | The JVM compiles hot code to machine code; deoptimization throws that code away when its assumptions break |
| **JFR** | JDK Flight Recorder, a low-overhead event recorder built into the JVM |
| **NMT** | Native Memory Tracking: JVM-tracked reserved and committed memory, including the heap |
| **RSS** | Resident set size: physical memory the process actually uses |
| **Allocation-free hot path** | Code that creates no new objects per operation, so it causes no GC work |
| **IRQ** | A hardware interrupt, which can steal CPU time from a latency-critical thread |
| **CPU isolation / pinning** | Reserving CPUs for specific threads so the OS does not schedule other work there |
| **C-state** | A CPU idle sleep level; deeper states save power but take longer to wake |
| **THP** | Transparent huge pages: 2 MiB memory pages that can help throughput but add latency spikes if misused |
| **eBPF** | Safe in-kernel tracing used to see where threads wait outside Java (needs root) |
| **Lab mode** | Opt-in mode where reversible host settings are applied by the operator with recorded rollback |
