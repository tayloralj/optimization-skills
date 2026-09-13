---
type: llm
weight: 2
---

The response should:
- identify the ~912 ms Full GC (preceded by an evacuation failure) as the dominant problem, far larger than the young pauses;
- explain that the heap is nearly full (live data around 1.4 GB+ of 2 GB) and/or allocation outpaces collection, and mention the humongous allocation as a contributing signal;
- recommend evidence before flags: a longer log window or JFR allocation data to find what allocates/retains, and checking whether spikes align with these pauses;
- propose at most a small number of concrete, justified changes (for example more heap headroom, reducing allocation or humongous objects) and say how to verify them.
Fail the response if it recommends a long list of unrelated JVM flags without tying them to the log evidence, or claims certainty about root cause from five lines without caveat.
