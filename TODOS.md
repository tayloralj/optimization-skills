# TODOs

## Validate Intel and AMD CPU profiling workflows

In progress. Runbooks, a synthetic Java attribution fixture, tests, and behavioral
eval cases are implemented. See [investigation status](docs/vendor-profilers.md)
for verified evidence and the concrete next live step.

- Prioritise Intel VTune and AMD uProf; investigate Intel PCM for system-level
  memory bandwidth, cache, frequency, and interconnect measurements.
- Verify supported CPU models, kernels, permissions, tool versions, and JDK
  21/25 compatibility on matching Intel and AMD hardware.
- Demonstrate bounded captures with resolved Java/JIT methods using known
  allocation, branching, and memory-access workloads.
- Measure profiler overhead and verify any improvements with repeated
  unprofiled runs.
- Investigate integration with the offline capture kit for hosts that cannot
  run an agent.
- Record real artifacts, commands, limitations, and tests; distinguish authored
  guidance from verified support. AMD results do not establish Intel support.

Starting references:

- [Intel VTune Java analysis](https://www.intel.com/content/www/us/en/docs/vtune-profiler/user-guide/2024-0/java-code-analysis-from-the-command-line.html)
- [AMD uProf CPU profiling](https://docs.amd.com/r/en-US/57368-uProf-user-guide/7.9.1.-Overview)
- [Intel PCM](https://github.com/intel/pcm)

Remaining gates: approved AMD tool availability, live uProf/IBS/Pcm captures and
overhead comparisons, JDK/VTune availability on the supplied Intel KVM guest,
host-side Intel core/uncore access (the guest has no PMU exposed), and scored
agent evals. Keep these open until actual vendor results meet the validation protocol.
