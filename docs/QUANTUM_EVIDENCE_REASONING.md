# Quantum and Emerging-Compute Evidence Reasoning

## Purpose

Knowledge Engine AI should reason about quantum-computing and emerging-compute evidence with the same provenance discipline used elsewhere in the system. Novel hardware or terminology must not receive a lower evidence bar.

This document coordinates with Knowledge Engine Core issue #498 and the portfolio Emerging Compute Evaluation policy in `project-orchestrator`.

No quantum runtime dependency is introduced here.

## Core reasoning rule

A claim about quantum or emerging compute is not one thing. The reasoning layer must preserve the distinction among:

- theoretical/complexity claims;
- classical simulation results;
- quantum-simulator results;
- physical-device measurements;
- error-mitigated/error-corrected hardware results;
- independent reproductions;
- comparisons against classical baselines.

When source material does not establish which class applies, report that uncertainty instead of inferring a stronger evidence class.

## Claim decomposition

For future quantum-related research answers, decompose material claims into at least:

1. **Problem claim** — what task/problem was actually studied?
2. **Method claim** — what algorithm, circuit, annealing method, sensing method, or other mechanism was used?
3. **Execution claim** — theory, simulation, or physical hardware?
4. **Scale claim** — what problem/resource scale was actually demonstrated?
5. **Comparator claim** — which classical baseline was used, and was it competitive/relevant?
6. **Performance claim** — correctness, runtime, sample complexity, solution quality, energy/cost, or another metric?
7. **Noise/reproducibility claim** — shots, replicates, seeds, calibration, noise model, error mitigation/correction, confidence/variance?
8. **Generality claim** — does the evidence support only a bounded benchmark, or a broader complexity/advantage statement?

## Evidence hierarchy is contextual, not promotional

Physical QPU execution is not automatically stronger evidence for every claim than a correct theoretical proof or a high-quality classical analysis. Evidence quality depends on the claim being tested.

Examples:

- a complexity theorem is primarily evaluated mathematically;
- a hardware-noise claim requires hardware evidence;
- a claimed practical speedup requires a credible classical comparator and end-to-end timing;
- a simulation can validate circuit logic but cannot establish physical-device performance by itself.

The AI layer should therefore ask: **what evidence class is appropriate for this claim?**

## “Quantum advantage” language gate

Do not use broad terms such as “quantum advantage,” “quantum supremacy,” or “quantum speedup” merely because:

- a quantum candidate beats one local baseline;
- a paper uses that language in its title/abstract;
- a simulator produces a lower objective value;
- a hardware run succeeds;
- the candidate uses more novel hardware.

For a Knowledge Engine local experiment, the strongest default phrase is:

**bounded benchmark superiority under the stated measurement contract**.

A broader claim requires source-supported evidence commensurate with the broader statement, including the relevant classical-comparator context.

## Missing-evidence behavior

When material fields are absent, explicitly surface the missing context. Examples:

- classical baseline unspecified;
- end-to-end timing missing;
- device/backend identity missing;
- shot count or replicate count missing;
- calibration/noise context missing;
- confidence/variance missing;
- simulator noise model unspecified;
- independent reproduction absent;
- cost omitted.

Do not fill these gaps from typical values or another paper unless the user explicitly asks for external contextualization and the distinction is made clear.

## Future experiment reasoning

When the Autonomous Engineering Scientist sends a bounded emerging-compute experiment to Knowledge Engine AI for interpretation, preserve:

- exact problem and measurement contract;
- exact classical baseline identity;
- candidate substrate/backend/environment;
- experiment lineage and attempt number;
- stochastic protocol;
- measured result distribution;
- cost and wall-clock context;
- independent verification refs;
- safety/provenance boundaries.

The AI layer may explain why the evidence supports retaining or rejecting a hypothesis, but it must not promote code, spend money, or redefine the measurement contract after seeing the result.

## Research opportunities

High-value future capabilities include:

- literature reviews that separate theoretical, simulated, and hardware-supported quantum claims;
- evidence tables comparing claimed speedups with the actual classical baselines used;
- reproducibility analysis across devices/research groups;
- quantum-chemistry method reviews that preserve Hamiltonian/model/basis/backend assumptions;
- tracking how a claimed advantage changes as classical algorithms improve.

These are research/evidence capabilities first. They do not require Knowledge Engine itself to run on a quantum computer.

## Activation trigger for code

Do not implement quantum-specific inference code solely from this roadmap. Code becomes justified when a real user/research workflow produces repeated evidence-classification errors or Core exposes a stable schema that the AI layer must interpret.
