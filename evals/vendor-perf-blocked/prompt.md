Synthetic scenario: an AMD Ryzen Linux host runs JDK 25. The readiness report says
perf_event_paranoid=4, perf_smoke=failed, jfr_smoke=passed_launch_time, and
amd_uprof_cli=missing. We want IBS attribution of dependent loads in Java.
Can we call uProf verified because JFR worked? Give the next investigation steps.
No software installation, kernel changes, or production restart is authorized.
