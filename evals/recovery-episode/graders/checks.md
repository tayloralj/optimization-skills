---
type: llm
weight: 2
---

The response should not declare gap fill production-ready from this evidence. It should name at least three of:
- verify completeness: every message sent was delivered (count delivered against sent), because a stalled client can
  leave a healthy-looking live histogram of the messages that did arrive;
- many recovery episodes with a seeded fault schedule and mixed gap sizes, including a loss immediately after a
  repair completes and losses that arrive during a repair, not five repeats of one large gap;
- count requests or round trips per episode (work amplification), not just elapsed time;
- repeat with realistic round-trip time and higher live rates, since loopback hides RTT-sensitive protocol behaviour;
- measure detection delay separately from repair time, starting the clock when the loss became observable, and
  report the effect on live traffic during episodes.
Fail if it accepts the 44 ms median or the live p99 as sufficient evidence.
