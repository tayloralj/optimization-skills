---
type: llm
weight: 2
---

The response should explain that the call site was previously mono- or bimorphic (C2 inlined it with a class check guard), and the third
Venue implementation made it megamorphic or failed the speculated type check, causing deoptimization, recompilation, and a slower
virtual dispatch. It should propose verifying with the JIT evidence (PrintInlining, JFR compilation/deoptimization events, or JMH), and
source-level options such as keeping the hot site to at most two receiver types, splitting the call site per venue type, or
restructuring dispatch. It should not recommend random global JIT flags as the main fix.
