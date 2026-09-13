---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

After yesterday's deploy, p99 latency of OrderRouter.route() doubled. JFR `jfr view deoptimizations-by-reason` shows thousands of
`class_check` deoptimizations in OrderRouter.route, which calls `order.venue().send(order)`. The deploy added a third Venue
implementation. What is going on and how do we fix it?
