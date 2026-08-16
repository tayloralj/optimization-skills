# Operator remediation

Use this guide only after the read-only preflight identifies a measurement that
is necessary and blocked. Exact policy differs by kernel, distribution,
container runtime, and organisation. The operator owns every command below.

## Decision order

1. Use a non-PMU fallback when it answers the question: JFR, async-profiler
   `ctimer` or wall clock, application metrics, or a controlled benchmark.
2. Reproduce on a profiling host whose policy already permits collection.
3. Grant only the required capability to a dedicated profiling service or
   wrapper after security review.
4. Change a sysctl temporarily, validate the exact event, then roll it back.
5. Persist a sysctl only when the security owner accepts the ongoing exposure.

Never silently broaden access because a profiling command failed.

## `perf_event_paranoid`

The integer is a policy hint, not a readiness test. Distribution patches can
add values or alter behaviour. Always smoke-test the event after a change.

For a standard Linux policy, an administrator can trial user-space-only access
temporarily:

```bash
(
  set -euo pipefail
  old_value=$(sysctl -n kernel.perf_event_paranoid)
  [[ "$old_value" =~ ^-?[0-9]+$ ]]
  changed=0

  restore_perf_policy() {
    sudo sysctl kernel.perf_event_paranoid="$old_value"
    [[ "$(sysctl -n kernel.perf_event_paranoid)" == "$old_value" ]]
    changed=0
  }
  finish() {
    status=$?
    trap - EXIT
    if (( changed )) && ! restore_perf_policy; then
      printf 'FATAL: perf_event_paranoid rollback failed; escalate immediately.\n' >&2
      status=1
    fi
    exit "$status"
  }
  trap finish EXIT
  trap 'exit 130' HUP INT TERM

  changed=1
  sudo sysctl kernel.perf_event_paranoid=2
  perf stat -e task-clock -- true
  perf stat -e cycles:u,instructions:u -- true
  restore_perf_policy
)
```

The first command captures the rollback value. `:u` asks for user-space counts
and avoids requesting kernel samples. Some profilers or system-wide collection
need a less restrictive value; do not lower it further without a stated need
and security approval.

If persistence is approved, use the distribution's managed sysctl mechanism
(commonly a reviewed file under `/etc/sysctl.d/`) and record the previous state,
owner, expiry, and rollback. Do not have an automation skill create that file.

## Capabilities

On kernels that support it, `CAP_PERFMON` is narrower than `CAP_SYS_ADMIN` for
performance monitoring. Attaching to another process may separately require
ptrace permission or `CAP_SYS_PTRACE`. Prefer scoping capabilities to a
dedicated systemd unit or approved wrapper. A file capability on a shared
`perf` binary affects every user allowed to execute it and therefore needs a
security review.

If an administrator considers a file capability, first resolve and record the
exact binary, package ownership, current capabilities, and an exact restoration
procedure:

```bash
perf_path=$(command -v perf)
getcap "$perf_path"
```

This guide intentionally does not provide a runnable `setcap` mutation.
`setcap -r` removes every pre-existing file capability and is not a safe generic
rollback. The administrator must preserve and restore the complete prior state,
or restore the package-owned binary, using the organisation's change process.

Do not substitute `CAP_SYS_ADMIN` merely because older documentation recommends
it. Package upgrades may replace a capability-bearing binary.

## Kernel symbols and `kptr_restrict`

`kptr_restrict` controls exposure of kernel addresses. Java user-space stacks do
not normally need it changed. If kernel-stack attribution is genuinely required,
have the security owner choose a scoped collection method and restore the prior
value immediately afterward. Do not publish raw kernel addresses.

## Containers

Host sysctls, container capabilities, seccomp, PID namespaces, and mounted
debug filesystems all affect profiling. A permissive container cannot override
a restrictive host policy. Prefer profiling the host process from an approved
host tool or run a dedicated debug deployment rather than making the production
container privileged.

Validate:

```bash
grep -E '^(CapEff|NoNewPrivs|Seccomp):' /proc/self/status
cat /proc/sys/kernel/perf_event_paranoid
perf stat -e task-clock -- true
```

## Production change record

Record the reason, host/service scope, approver, exact before/after values,
start and expiry times, validation command, evidence location, and rollback
result. Remove capabilities or temporary policy changes when collection ends.
