---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Our payments service (Java 21, runs as user `payments` on a locked-down RHEL production VM) gets latency spikes
around 18:00 every day. Nobody can install Codex or Claude on that box and I don't have a shell there; the ops team
will run whatever I send them and send files back. How do we capture what's happening and analyse it here?
