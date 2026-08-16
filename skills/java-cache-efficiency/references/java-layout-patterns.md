# Java layout and locality patterns

## False sharing

Use JOL to confirm field offsets and a multi-thread benchmark to confirm that
separating independently written fields improves the target metric.

`@jdk.internal.vm.annotation.Contended` may require:

```text
Javac: --add-exports java.base/jdk.internal.vm.annotation=ALL-UNNAMED
Java:  --add-exports java.base/jdk.internal.vm.annotation=ALL-UNNAMED
-XX:-RestrictContended
```

It is an internal annotation, changes memory footprint, and should be isolated
behind a well-tested component. LMAX-style sequence classes may already include
padding; inspect the library version before adding more.

Record `RestrictContended`, `ContendedPaddingWidth`, object alignment,
compressed references, and compact-header state. Contended groups isolate
selected fields within one object; they do not control placement between
independently allocated objects. Compare before/after JOL output, retained heap,
and GC behaviour. Agentless JOL estimates can have lower confidence than
instrumented layout output; state which mode was used.

## Read-mostly publication

When many publisher threads contend on a subscriber collection that changes
rarely, build a defensive array/list copy under membership-update synchronization,
never mutate it afterward, and publish it through a volatile reference. The hot read path
then iterates the snapshot. Test removal, ordering, exception isolation, and
visibility. A read-write lock is not automatically cheaper for short writes.

## Queue and buffer footprint

Calculate:

```text
retained bytes approximately slot count times per-slot object and buffer size
```

Then add headers, references, alignment, queue metadata, and duplicate outbound
copies. Validate configured maximum payload against every fixed-size event
buffer and copy operation. Test oversize handling explicitly.

## Direct and off-heap memory

Direct buffers can reduce copying in some I/O paths but move pressure outside
the Java heap. Track native memory, cleanup/lifetime, bounds, pooling, partial
writes, failure recovery, and diagnostic visibility. Compare end-to-end rather
than allocation rate alone.
