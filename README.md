# Aged Credits Dashboard

Light-green Abra Health dashboard tracking aged patient credits across PA, NJ, and CT — staff use it to work refunds and account resolutions oldest-and-largest first.

Live URL: _to fill in after first GitHub Pages push_

## Files

| File | Purpose |
|---|---|
| `template.html` | Clean template with `__DATA_PLACEHOLDER__`. **Edit this** when changing UI. |
| `build_dashboard.py` | Reads OneDrive CSVs → emits `dashboard.html` + `index.html` |
| `dashboard.html` / `index.html` | Generated, ready to serve (do not hand-edit) |
| `dashboard_data.json` | Embedded payload, also written standalone for inspection |
| `snapshots/snapshot_YYYYMMDD.json` | Monthly point-in-time totals used for the Overview MoM card |

## Data sources

- **NJ + PA**: latest `*.csv` in `OneDrive/ABRA RCM - NJ/Credit NJ and PA/`
- **CT**: latest `*.csv` in `OneDrive/ABRA RCM - CT/Credit Accts/CT Credit Dashboard/`

CT file has no `Clinic` column, so the Clinic filter uses patient City as a proxy.

## Monthly refresh

```bash
cd "/Users/Admin/Desktop/Claude/Credits Dashboard"
python3 build_dashboard.py
```

Staff edits (Status / Assigned / Action / Date Worked / Remarks) live in Firebase, **not** in the embedded data — rebuilds preserve them automatically.

## Filters

- **Aging bucket** (multi-select, oldest first): 0-30 → 5+ yrs
- **Clinic** (multi-select, PA consolidated per CLAUDE.md)
- **Status**: In Progress / Completed
- **Assigned**: PA & CT → AB / KC / LE / LJ — NJ → JR / MS
- **Action**: PPO Refund Requested / Patient Refund Processed / Patient Refund Requested / Medicaid Refund Processed

## Sort

Rows default to oldest bucket first, then highest credit amount (most negative) first — same prioritization the team agreed to work.

## Firebase

Per [[feedback_firebase_separate_projects]], this dashboard needs its own project. Suggested name: **credits-abra**.

1. Create project `credits-abra` in the Firebase console
2. Realtime Database → start in test mode → copy database URL
3. Replace the placeholder URL in `template.html`:
   ```js
   databaseURL: 'https://credits-abra-default-rtdb.firebaseio.com'
   ```
4. Re-run `python3 build_dashboard.py`
5. Recommended security rules (matches PA Denials pattern): allow read/write only on the `credits/$key/$field` shape, per-field scoping

## Auth

Dashboard password: `Credits2026`

## TODO

- [ ] Create Firebase `credits-abra` project + paste real DB URL
- [ ] First push to `ABRARCM/CreditsDashboard` (GitHub Pages)
- [ ] Wire monthly auto-update (launchd plist; use `/bin/bash` wrapper per [[feedback_launchd_bash_wrapper]])
