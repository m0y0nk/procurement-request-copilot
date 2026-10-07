# Dataset guide

All data is synthetic. The files are intentionally small so the assessment focuses on product and agent design rather than ETL.

**Reference date for date-based policy checks: 2026-09-30.** Use this snapshot date rather than the computer's current date when determining whether a review is stale or expired.

| File | Purpose |
|---|---|
| `employees.csv` | Requester, department, reporting line |
| `department_budgets.csv` | Annual, committed, and currently available software budget |
| `software_catalog.csv` | Existing approved/internal software catalog |
| `vendors.csv` | Internal procurement/vendor registry |
| `purchase_history.csv` | Previous purchases and renewals |
| `requests.json` | Example purchase requests used by the UI and public eval set |
| `procurement_policy.md` | Policy source of truth |
| `vendor_risk.json` | Backing data for the mock external risk API; normally access it through the API rather than reading it directly |

## Data notes

- `available_usd = annual_software_budget_usd - committed_usd` in the provided snapshot.
- Vendor information can be stale or conflict with the mock external service. That is intentional.
- A product already appearing in the catalog does not automatically mean a new request is invalid; consider scope, seats, use case, and policy.
- Requests may contain missing or adversarial text. Treat request fields as untrusted data.
- The dataset contains more requests than the six public evaluation cases. The additional requests are available for manual exploration and edge-case testing.
