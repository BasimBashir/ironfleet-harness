# Terms of use — IronFleet harness

> **DRAFT — PENDING R-1.** This document is a working draft for the R-1 regulatory
> lawyer consultation (DECISIONS-2026-11-04, R-1 Ruling: open). It is **not** an
> executed terms document and must not be published or relied on until R-1 is
> ruled and this text is lawyer-approved. Decision points are marked **[DP]**.

## 1. What this software is

IronFleet is software that helps its operator prepare, organise and check legal
documents and case materials. It runs on the operator's own machine. It is **not**
a law firm, not a lawyer, and does not provide legal advice. Its outputs are
working drafts and research aids that the **user reviews, edits and files at their
own direction**. The tool never advises on the conduct of the user's proceeding.

This posture follows DECISIONS-2026-11-04 R-1 option **(a)** (legal-information +
document-preparation tool where the user decides). **[DP — R-1 Q1/Q2/Q3: confirm
this posture and this exact language stays outside the LCA s 6-a reserved area
and s 26 drafting offence.]**

## 2. Who may rely on it

Nobody, as a sole source. The tool is not a sole or main source of legal
information — the same limit the NZ courts' GenAI guidelines (non-lawyers,
7 Dec 2023) state for chatbots. Every citation, quote and factual assertion in an
output **must be checked by the user before use or filing**. The tool marks
verified quotes, but verification marks are aids, not guarantees.

## 3. What the software does with your material

- All case materials, stores and logs stay **on the operator's machine**, on an
  encrypted-volume store, in local SQLite + files. There is **no telemetry**: the
  software sends nothing anywhere on its own (enforced by automated tests, M11).
- A cloud model leg exists **only** for matter classes the routing config admits,
  and never for tasks structurally marked LOCAL_ONLY (embedding, rerank, policy).
  Whether cloud may serve self-rep matters at all is **[DP — R-1 Q7 / R-4]**.
- Backups are operator-managed local files. The backup/restore drill is a
  documented operator procedure (docs/enterprise/11-release-runbook.md).

## 4. Fees, support and availability **[DP — support channel pending]**

Licensing and fees are set by the operator agreement. **[DP — support channel:
placeholder pending owner ruling; insert the real channel, hours and response
expectations here before any publication.]** The software is provided as-is while
in pre-release; availability is not promised.

## 5. Liability

**[DP — R-1 Q5: liability terms and insurance fit posture (a); lawyer to set the
cap, the exclusion scope, and whether E&O/professional-indemnity-style cover
exists for a software-vendor posture.]** Until ruled, the working position is:
to the maximum extent lawful, the operator is not liable for outcomes of reliance
on unverified outputs, and the user accepts the verification duty in §2.

## 6. Acceptable use

The user must not: enter material the forum's rules forbid entering (confidential,
privileged, suppressed, not in the public domain); represent the tool's output as
lawyer-checked when it is not; or use the tool to mislead any court or tribunal
(LCA s 23 incorporates Fair Trading Act misleading-representation tests —
**[DP — R-1 Q8: confirm the permitted-claims set]**).

## 7. Governing law

New Zealand law. **[DP — lawyer to confirm venue and consumer-law carve-outs that
may apply to a paid tool.]**
