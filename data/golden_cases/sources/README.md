# Golden-case source documents (bring your own)

This folder holds the judgments and source documents the golden evaluation cases in
`data/golden_cases/` are graded against. They are **not** part of the repository:
every user supplies their own copies, which stay on that machine only (`.gitignore`
excludes everything here except this file).

To run the evaluation scripts (`scripts/check_golden.py`, `scripts/run_ab.py`, …):

1. Obtain each judgment named in a case file's `# source:` header (the first line of
   every `data/golden_cases/*.yaml`) from a source you are licensed to use (court
   websites, your firm's research service, …).
2. Save it here under that exact file name, inside the set folder the case belongs to
   (for example `Set_2/`).
3. Run the script; any missing source is reported by name.

The application itself never needs this folder: matters get their documents through
**Documents → Upload / Ingest** in the app.
