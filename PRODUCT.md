# Product

## Register

product

## Users

Chartered accountants and audit-firm staff, working on their own Windows machines during month-end / quarter-end statutory close. They process folders of similar government-portal PDFs — GSTR-1, GSTR-3B, TDS (ITNS-281), PF ECR, ESIC, PTRC — and need clean, verified figures they can drop straight into working papers. Two contexts: a solo practitioner who wants speed and trust in the numbers, and firm staff whose output gets reviewed by a senior. The data is client financial data, so it must never leave the device.

## Product Purpose

A fully offline browser tool (Python compiled to WebAssembly via Pyodide) that auto-detects a return type from each PDF, parses it into a normalized flat ledger, runs sanity checks, flags exceptions, and rolls everything up into a compliance overview. Success = the auditor trusts the numbers at a glance, spots the exceptions in seconds, exports to Excel/CSV for working papers, and never worries about a byte leaving the machine.

## Brand Personality

Premium, restrained, institutional. The register of a private-bank statement or an audit report, not a SaaS dashboard. Voice: precise, understated, confident. It should feel like a trustworthy instrument — calm control and gravitas, earned by accuracy and alignment rather than decoration.

## Anti-references

- **Consumer fintech apps** — bubbly rounded UI, pastel gradients, emoji, mascots.
- **Cluttered enterprise ERP** (Tally / SAP) — dense grey forms, tiny fonts, no hierarchy.
- **Playful startup** — bright illustrations, bouncy motion, informal copy.
- **Generic SaaS dashboard** — gradient hero-metric cards, purple accents, identical icon+heading card grids.

## Design Principles

- **Numbers first, chrome last.** Data legibility and exact alignment beat any decoration; tabular figures, no rounding surprises.
- **Trust through precision.** Every flag is traceable to its source file and challan reference; the interface earns confidence by being exact, not by claiming to be.
- **Quiet confidence.** Restraint signals rigor. Hierarchy comes from scale, weight, and space, not color or effects.
- **Reviewability.** Exceptions surface first; the auditor scans a page, never hunts for the one row that needs attention.
- **Offline is the feature.** The "nothing leaves this device" guarantee is made visible and reassuring, not buried in fine print.

## Accessibility & Inclusion

WCAG 2.1 AA. Body text ≥ 4.5:1; status is never color-only (each state carries a text label). Data tables are keyboard-navigable with visible focus. Honors `prefers-reduced-motion`. Must stay legible and responsive on modest office hardware and at typical office-monitor DPI.
