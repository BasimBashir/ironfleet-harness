# 10 — Jurisdiction Pack Format (M9)

**Date:** 2026-11-09 · **Status:** implemented as the M9 plugin prototype
(`ironfleet-legal/mcp/harness/module_e/`); this document is the format spec.
**Companions:** NEXT_STEPS §9 (M9 row) · [09-moot-gate-design.md](09-moot-gate-design.md)
· [plan](../../plans/2026-11-09-m9-enforcement-appeal-settlement.md).
**Rulings honoured:** D-P3 (a jurisdiction is a data pack, never a code fork) ·
D-P5 (dates/rules/fees are deterministic kernels; the model never counts days) ·
D-P8 / W2 (law supply stays operator-supplied; NZLII NO-GO; every value carries a
`source` record of where the operator got it).

## 0. The principle

Everything jurisdiction-specific lives in **data files loaded by
`JurisdictionLoader`** — never in an `if jurisdiction == "nz"` branch in code.
Adding or correcting a jurisdiction is a data edit plus a licence record, not a
code change. A pack section the operator has not supplied ships **absent**; the
kernels refuse loudly (`pack 'xx' carries no appeal section`) rather than invent
law. Framing as everywhere: maximum defensibility — nothing here promises a court
accepts an output.

## 1. Layout

```
module_e/vendored/data/config/jurisdictions/
  <code>.json            # the pack: one file per jurisdiction (nz, au, uk, ...)
  <code>_holidays.json   # calendars (national + regional) the kernels read
```

`<code>.json` sections: `interest`, `limitation_periods`, `statutory_demand`,
`penalty_clause`, `solvency`, `security_interest`, `without_prejudice`,
`holidays_file` (all pre-existing), plus the **M9 sections**:

| Section | Fields | Kernel that reads it |
|---|---|---|
| `appeal` | `days`, `day_type` (working\|calendar), `rule_ref`, `source` | `post_judgment.appeal_window` → deadline kind `appeal` |
| `enforcement` | `options[]` {code,label,rule_ref}, `issue_rule_ref`, `source` | `post_judgment.enforcement_options` / `enforcement_issue_date` |
| `settlement` | `day_type`, `rule_ref`, `source` | `post_judgment.settlement_milestone` → deadline kind `settlement` |

Optional pack-level extras the product also treats as data: court forms index,
filing fees, service rules, forum thresholds, court AI-use guidance, corpus
pointer, golden cases. **None of these is code**; when a module needs one it
reads it through the loader and refuses when absent.

## 2. Source discipline (W2 / D-P8)

Every legal value in a pack carries a `source` string naming the operator-supplied
file and version (e.g. `"operator-supplied export: High Court Rules 2016.md
(Desktop/nz), r 20.4(2)(b)"`). The corpus manifests
(`harness-core/data/corpus/statute_sources.yaml`) already record
path / act / version / licence / source_url / retrieved for ingested statutes;
pack values point at the same operator files. NZLII stays NO-GO; external legal
data only through the egress gate with a licence check.

## 3. The NZ pack (completed in M9)

`nz.json` now carries, all quoted from the operator-supplied exports on
`Desktop/nz`:

- **appeal**: 20 **working days** from the decision, `High Court Rules 2016
  r 20.4(2)(b)` (leave applications: Senior Courts Act 2016 s 58(3),(5), same
  20 working days). Computed through the NZ working-day calendar, which includes
  the Companies Act 1993 s 2 Christmas closure (25 Dec–2 Jan plus the
  observed-Monday rule) — the closure is calendar data, and the golden case
  7 Dec 2026 → 13 Jan 2027 pins it.
- **enforcement**: the r 17.3(1) process list (attachment, charging, sale,
  possession, arrest, sequestration orders) + the r 17.3(3) rule that no process
  issues before the judgment's payment period expires — the kernel refuses an
  issue date before that period ends rather than clamping.
- **settlement**: milestone day_type `calendar` — a product convention, recorded
  as such in `source`, not a statute; every milestone date is still
  kernel-computed.

au/uk packs carry no M9 sections yet: the loader reads them with defaults and
the kernels refuse with a clear message until the operator supplies the values.

## 4. How the kernels consume the pack

- `post_judgment.appeal_window(service_date)` → `add_working_days` or calendar
  addition per `appeal.day_type`; refuses a caller-supplied `due`.
- `post_judgment.enforcement_options()` → the pack list verbatim.
- `post_judgment.enforcement_issue_date(...)` → r 17.3(3) guard.
- `post_judgment.settlement_milestone(service_date, days)` → deadline kind
  `settlement`, registered in the dossier deadlines register with
  `source=kernel`.
- `deadlines.register` / `ironfleet_deadline_register` accept the new kinds
  `appeal` and `settlement` alongside `filing` and `statutory_demand`; the
  caller-supplied-`due` refusal is unchanged.

## 5. Exports that read the pack + dossier (also M9)

- `ironfleet_calendar_export` — `.ics` (hand-written VEVENTs) from the deadlines
  register, local file only, path contained to the workspace.
- `ironfleet_export_court_pack` — court-format docx (stdlib zipfile + OOXML) or
  pdf (hand-rolled PDF 1.4) from the facts + open deadlines; stdlib only because
  §10 bars new dependencies without a dated ruling.

## 6. Golden cases

`ironfleet-legal/tests/test_m9_post_judgment.py` pins: appeal 2026-11-05 →
2026-12-03, 2026-12-07 → 2027-01-13 (Christmas closure), 2026-03-02 → 2026-03-30;
settlement 30 calendar days 2026-03-02 → 2026-04-01; enforcement option codes
from the pack; r 17.3(3) refusal; `due`-refusal on every new kind; .ics content;
docx zip validity; PDF header/trailer. `test_jurisdictions.py` (AU/UK calendar
round-trip) stays green — 59 passed in the M9 test batch, 145 in the full
plugin suite at this commit.
