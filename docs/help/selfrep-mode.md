# IronFleet — self-rep mode help

IronFleet in self-rep mode is your case workspace: it keeps your documents in one
place, helps you draft and check what you file, and shows what is happening to
your case. It runs entirely on your own computer.

**This tool is not a lawyer and this is not legal advice.** It is a document and
research aid: you review, edit and file everything yourself, and **you are
responsible for what you file**. It is not a sole or main source of legal
information — if you can, check with a lawyer.

## What it does for you

- **Your case home** shows where your case is up to and what to do next.
- **Drafting help**: you point the tool at your stored documents; it drafts in
  your matter's own words and marks which quotations it could verify against the
  source — check every one before use.
- **The lawyer-now block**: at certain points the tool shows a reminder to
  consider getting legal help (community law centres, duty lawyers). It is a
  reminder block, not a referral and not a gate.
- **Bigger, clearer screens**: self-rep mode uses larger text and simpler
  screens than firm mode.
- **Everything stays on your computer.** The software sends nothing anywhere on
  its own. If a cloud model is configured for your matter type, that one dispatch
  is traced locally; privileged matters never leave local models.

## The three duties (the courts ask every GenAI user)

1. **Check everything before you file.** Generative AI can invent cases and
   quotes that look real but are not. The tool flags unverifiable quotes; you
   resolve them.
2. **Enter nothing confidential** — nothing private, privileged, suppressed or
   not in the public domain. If you have, contact the registry.
3. **Disclosure**: courts currently ask about AI use only if they ask you. The
   tool states this rule when you are preparing a filing; tell the court or
   tribunal the truth if asked.

## Common tasks

```bash
harness session --new --matter <ref>      # a working session on your matter
harness session --turn --prompt "..."     # one agent turn in that session
```

`harness` is the terminal command that comes with your install. Self-rep users
normally work in the web screen; the commands above are the same work from a
terminal. Your documents live under the IronFleet store folder on your computer's
encrypted volume — do not move or rename that folder.

## If something breaks

If a long-running screen dies, it writes a log under the IronFleet store's
`crash/` folder (the newest log is the one to send — to **[support channel
placeholder, pending owner ruling]** — and nothing is ever sent automatically).
If a result looks wrong, do not file it: fix the draft or ask for help first.
