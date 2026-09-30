# Impact and viability

**Evidence the problem is real:**

> "Retailers continue to manage inventory, reconciliation, and reporting through custom-built Excel sheets. This is not due to a lack of awareness or access to alternatives, but rather because many existing tools fail to align with how these businesses actually operate. Each business had developed its own customised Excel workflows, tailored precisely to its operations."
> **Ahmed Sameh, CMO, Fortis**, on research with 130+ UAE SMEs ([MENAFN, April 2026](https://menafn.com/1111035482/Despite-the-AED-543B-digital-push-64-of-UAE-SMEs-run-core-operations-on-Excel))

- **64% of UAE SMEs run core operations on Excel**, more than use accounting systems (51%) or POS systems (34%) (Fortis, April 2026). AutoStack is built for exactly this: it learns each office's own spreadsheet routine instead of replacing it with a new tool.
**First-hand evidence: TÜV Rheinland, Dubai.** A member of Team Activation hand-built 8 automations for TÜV Rheinland's certification teams, and TÜV staff use them today:

| Tool (hand-built, in use) | By hand | With the tool |
|---|---|---|
| Certificate invoices: reads invoice PDFs and fills the certificate in TÜV's internal portal | 1–2 hours for 2–3 people per 20 invoices | **20 invoices in 5 minutes** |
| Shipment certificates on an internal portal | 2–3 hours per certificate (TÜV estimate from the task breakdown) | **5–7 minutes**; about **40–60 hours a month** freed at 20 certificates a month |
| Factory-audit reports | Matching each factory's document list to the audit checklist by hand | 47 checklist items across 19 sections matched and 12 photos placed per run (~8,300 lines of code) |

Each of these needed a developer for weeks. AutoStack exists so the next office doesn't.

> "I would use it. It feels like it would save us a lot of time."
> **Technical Officer (Conformity Assessment Engineer), TÜV Rheinland Middle East**, after seeing AutoStack (one of 5 office and factory workers who gave early feedback, September 2026)
>
> "We use Excel for a lot of our work, so this would save us time."
> **Resident Engineer, ACE International Consulting Engineers, Dubai**

**AutoStack on a TÜV-style task (timed).** From 3 example edits on an invoice-review sheet with invented data, AutoStack identified the routine, planned the rule, wrote and self-checked the code, tested it on a copy of the sheet, dry-ran it and ran it live on the 5 remaining invoices in **0.4 seconds of processing** (offline generator, simple routine; a Gemini call adds a few seconds; the person's edits and approval click are not counted). This is a simpler routine than the internal-portal tools above, which AutoStack cannot build yet because it writes CSV; it shows the loop, not a like-for-like replacement.

**Who it's for:** offices of 2 to 50 people whose work already lives in spreadsheets, such as trading companies, clinics, facility services, logistics and accounting firms.

**Illustrative savings (conservative, with the maths shown):**

| Input | Value | Basis |
|---|---|---|
| Admin salary | AED 6,000 / month | **Assumption.** Typical UAE admin or accounts clerk; replace with your own figure |
| Working hours | 48 h / week | UAE private-sector maximum |
| Hourly cost | ≈ AED 29 | 6,000 × 12 ÷ (48 × 52) |
| Hours saved | **3 h / week** | A third of the 9 h/week reported in Parseur's US survey, for margin |
| **Saving per employee** | **≈ AED 4,150 / year** | 3 × 29 × 48 working weeks |
| **5-person back office** | **≈ AED 20,700 / year** | Before counting fewer errors or late-filing penalties |

**Why it's viable:**

- **Zero setup cost:** it runs on hardware the office already owns (measured on Windows at under 100 MiB RAM and under 1% idle CPU).
- **Zero running cost:** no per-task fees, and the offline AI mode means no AI bill at all.
- **Zero automation expertise needed:** the office doesn't design anything; it reviews and approves what AutoStack proposes.
- **Built for what's coming:** consistent, audited back-office steps make the 2027 e-invoicing switch easier, because the data is already clean and traceable.

**Path to adoption:**

| Stage | What happens |
|---|---|
| Week 1 | Install locally, point AutoStack at the team's shared folder, let it observe |
| Weeks 2–4 | First patterns appear; the team approves the ones it trusts |
| Month 2+ | Approved automations run on schedule; templates are shared between branches through the signed registry |
| Next | Pilot with 3 UAE small offices, starting with the TÜV Rheinland teams already using our hand-built tools (Dec to Feb), to replace illustrative savings with measured hours |

[← Back to README](../README.md)
