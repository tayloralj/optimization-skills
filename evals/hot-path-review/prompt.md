---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill]
---

Please review this market-data handler for latency problems. It is called about 200,000 times per second on one thread.

```java
public final class QuoteHandler {
    private final Map<Long, Double> lastPrice = new HashMap<>();
    private final Logger log = LoggerFactory.getLogger(QuoteHandler.class);

    public void onQuote(long instrumentId, double bid, double ask) {
        Double previous = lastPrice.put(instrumentId, (bid + ask) / 2);
        String line = String.format("quote %d bid=%.4f ask=%.4f prev=%s", instrumentId, bid, ask, previous);
        log.debug(line);
        List<Double> spreads = new ArrayList<>();
        spreads.add(ask - bid);
        publish(spreads);
    }

    private void publish(List<Double> spreads) { /* ... */ }
}
```
