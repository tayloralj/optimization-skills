#!/usr/bin/env python3
"""Print ranked, read-only next steps for a Linux JVM symptom."""
import argparse
import json
import re

ROUTES = [
    ("memory", r"rss|resident|native|off.?heap|oom|out of memory", "java-native-memory", "heap, NMT, cgroup and OOM evidence"),
    ("gc", r"gc|garbage|pause|safepoint", "java-gc-tuning", "GC and safepoint logs plus JFR"),
    ("latency", r"latency|p99|tail|jitter|spike|slow request", "java-latency-measurement", "measurement validity, JFR and host jitter"),
    ("blocked", r"hung|stuck|deadlock|blocked|lock|wait", "java-async-profiler", "thread dumps, lock and off-CPU evidence"),
    ("crash", r"crash|restart|coredump|core dump|segfault|hs_err", "java-offline-capture", "service journal, coredump and JVM crash evidence"),
    ("cpu", r"cpu|hot|throughput|busy|high load", "java-flight-recorder", "JFR CPU, GC, JIT and safepoint context"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symptom", required=True, help="plain-language JVM symptom")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()
    text = args.symptom.strip()
    if not text:
        parser.error("--symptom cannot be empty")
    matches = []
    for name, pattern, skill, evidence in ROUTES:
        if re.search(pattern, text, re.I):
            matches.append({"route": name, "skill": skill, "evidence": evidence})
    if not matches:
        matches = [{"route": "unknown", "skill": "java-performance-investigation", "evidence": "objective, workload classification, readiness, and a bounded baseline"}]
    result = {"symptom": text, "hints": matches, "readiness": "profiling-readiness", "offline": "java-offline-capture"}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("symptom=" + text)
        print("first=profiling-readiness")
        print("offline=java-offline-capture")
        for i, hint in enumerate(matches, 1):
            print(f"hint_{i}={hint['skill']}: {hint['evidence']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
