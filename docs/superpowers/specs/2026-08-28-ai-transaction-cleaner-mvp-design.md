# AI Transaction Cleaner MVP Design

## Goal
Build a small-business/bookkeeping workflow that turns messy bank transaction files into a reviewed, categorized, bookkeeping-ready Excel export.

## Product scope
The MVP is intentionally narrow. A user uploads a CSV or XLSX file containing transaction data. The app normalizes the input to a standard transaction schema, suggests a category and confidence score, routes uncertain rows to human review, remembers explicit user corrections as deterministic rules, shows a simple completion summary, and exports a cleaned Excel workbook.

The MVP does not include bank APIs, Plaid, QuickBooks/Xero integration, PDF/OCR, payroll, invoice processing, tax calculation, SaaS billing, or a mobile app.

## Reuse strategy
Use MoneyFlow as the main application base because it already provides Streamlit UI, pandas-based parsing, categorization, SQLAlchemy persistence, optional AI-provider abstractions, dashboards, and a simple local-first deployment model.

Treat bankstatementparser as a future input-parsing component rather than the primary application. Its broader CSV/OFX/MT940/CAMT/PDF parsing can be added after the core CSV/XLSX workflow is validated.

Do not base the MVP on NumbyAI because its React + FastAPI + Ollama stack adds unnecessary deployment and maintenance complexity for the first release.

## Primary workflow
1. Upload CSV or XLSX.
2. Detect likely date, description, amount, debit, and credit columns.
3. Normalize into a canonical table: Date, Description, Amount, Original Description.
4. Categorize each transaction using learned deterministic rules first, then existing keyword rules, then AI fallback where enabled.
5. Attach a confidence score and review status.
6. Route low-confidence or ambiguous transactions to Needs Review.
7. Let the user confirm or change the category.
8. Persist explicit user corrections as learned merchant/description rules.
9. Recalculate completion statistics.
10. Export a cleaned XLSX workbook.

## Canonical transaction fields
- Date
- Description
- Amount
- Suggested Category
- Final Category
- Confidence
- Review Status
- Original Description
- Rule Source

## Categorization order
1. Exact learned rule from previous user correction.
2. Normalized merchant/description learned rule.
3. Deterministic keyword/category rules.
4. AI suggestion if configured.
5. Needs Review when no reliable category can be determined.

The system must never silently force a low-confidence AI guess into Final Category.

## Confidence and review
Use three broad states rather than pretending the model has calibrated probability precision:
- High: deterministic learned rule or strong known rule.
- Medium: plausible category suggestion requiring optional review.
- Low: ambiguous description, generic e-transfer, unknown merchant, or conflicting signals.

Low-confidence rows default to Needs Review.

## Learned rules
When a user explicitly changes or confirms a category, the app may save a reusable rule based on a normalized merchant/description key. The UI must show that the rule is being learned and allow the user to opt out for one-off transactions.

Example: `JASON WANG` -> `Contractor Expense`.

Rules must be deterministic and inspectable. AI must not modify saved rules on its own.

## UI
### Upload
- Drag-and-drop CSV/XLSX.
- Show detected columns before processing.
- Reject files missing a usable date, description, or amount/debit-credit representation.

### Review table
Show transaction, suggested category, confidence, final category, and review status. Default the view to rows that need review.

### Summary
Show total transactions, auto-categorized count, needs-review count, reviewed count, and automation rate.

### Export
Produce `Cleaned_Transactions.xlsx` with the canonical transaction fields and a summary sheet.

## Data handling
Default local-first behavior. Do not persist uploaded transaction data unless the user explicitly saves the session. Learned rules can be stored locally in SQLite. Avoid logging full transaction descriptions or account identifiers.

## Testing
- CSV with single Amount column.
- CSV/XLSX with separate Debit/Credit columns.
- Positive income and negative expense normalization.
- Malformed and blank rows.
- Duplicate-looking descriptions.
- Generic e-transfers.
- Learned-rule precedence over AI.
- Low-confidence rows never auto-finalized.
- Export preserves final category and review status.
- No real bank/customer data in tests; use synthetic fixtures only.

## Success criteria
The MVP is successful if a representative synthetic file of several hundred transactions can be uploaded, normalized, categorized, reviewed, and exported without manual spreadsheet cleanup, and if most obvious merchants are auto-categorized while ambiguous transfers remain clearly queued for review.

The business validation target is operational: reduce a typical 30-60 minute manual categorization workflow to roughly 5-10 minutes of review, without sacrificing human control over ambiguous rows.

## Next phase only after validation
- bankstatementparser integration for OFX/QFX/MT940/CAMT/PDF.
- Bulk multi-file import and de-duplication.
- Bookkeeper/client rule libraries.
- Accounting-system export formats.
- Hosted multi-user deployment.
