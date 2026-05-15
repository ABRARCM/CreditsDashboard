"""
Credits Dashboard — build pipeline.

Reads the monthly OneDrive Aged Credit CSV (NJ + PA), cleans it, consolidates
PA clinics per CLAUDE.md, computes an oldest-age bucket per row, sorts rows
(highest credit first within oldest bucket), and emits an embedded JSON
payload merged into template.html -> dashboard.html / index.html.

CT is scaffolded empty until the CT CSV is added to OneDrive.

Run:
    python3 build_dashboard.py
"""

import glob
import json
import os
import re
import sys
from datetime import datetime

import pandas as pd

ROOT = "/Users/Admin/Desktop/Claude/Credits Dashboard"
ONEDRIVE = "/Users/Admin/Library/CloudStorage/OneDrive-ChildSmilesGroup,LLC(2)"
NJPA_DIR = f"{ONEDRIVE}/ABRA RCM - NJ/Credit NJ and PA"
CT_DIR = f"{ONEDRIVE}/ABRA RCM - CT/Credit Accts/CT Credit Dashboard"

# Raw CSV columns -> display bucket name. Multiple raw cols can roll up to one bucket.
RAW_TO_BUCKET = [
    ("Bal_0_30",       "0-30"),
    ("Bal_31_60",      "31-60"),
    ("Bal_61_90",      "61-90"),
    ("Bal_91_120",     "91-120"),
    ("Bal_121_365",    "121-365"),
    ("Bal_366_730",    "1-3 yrs"),
    ("Bal_731_1095",   "1-3 yrs"),
    ("Bal_1096_1460",  "4+ yrs"),
    ("Bal_1461_1825",  "4+ yrs"),
    ("BalOver1825",    "4+ yrs"),
]
# Ordered list of display buckets (oldest last)
BUCKET_ORDER = []
for _, b in RAW_TO_BUCKET:
    if b not in BUCKET_ORDER:
        BUCKET_ORDER.append(b)
# Back-compat alias so the rest of the file keeps working
AGING_COLS = RAW_TO_BUCKET

# PA clinic consolidation (per CLAUDE.md)
PA_CONSOLIDATE = {
    "Allentown OS":     "Allentown",
    "Allentown OR":     "Allentown",
    "Scranton West":    "Scranton",
    "Scranton OR":      "Scranton",
    "Wilkes-Barre East":"Wilkes-Barre",
    "Wilkes-Barre OR":  "Wilkes-Barre",
    "Hazleton OR":      "Hazleton",
    "Bartonsville OR":  "Bartonsville",
    "Reading OR":       "Reading",
}

# Drop garbage clinics (PA hospital placeholder, NJ "no billing")
DROP_CLINIC = {
    "*NO BILLING* S4K Hospitals *NO BILLING*",
    "CASC NO DENTAL BILLING",
}

# Tokens the OD query writes into spacer and TOTALS rows (PatNum / Clinic / state).
GARBAGE_TOKENS = {"", "-----", "TOTALS:", "TOTALS", "NAN", "NONE"}


def is_real_row(row):
    """True only for legit patient rows (drops spacer + TOTALS + blanks)."""
    pn = str(row.get("PatNum") or "").strip().upper()
    if pn in GARBAGE_TOKENS:
        return False
    if not pn.isdigit():
        return False
    clinic = str(row.get("Clinic") or "").strip().upper()
    if clinic in GARBAGE_TOKENS:
        return False
    state = str(row.get("Clinic_state") or "").strip().upper()
    if state not in {"PA", "NJ", "CT"}:
        return False
    return True


def latest_csv(dir_path, pattern="*.csv"):
    files = glob.glob(os.path.join(dir_path, pattern))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def parse_money(v):
    if pd.isna(v): return 0.0
    s = str(v).strip().replace("$", "").replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1]
    try:
        x = float(s)
    except ValueError:
        return 0.0
    return -x if neg else x


def parse_date(v):
    if pd.isna(v) or not str(v).strip():
        return ""
    s = str(v).strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def clean_guarantor(s):
    if pd.isna(s): return ""
    s = re.sub(r"\s+", " ", str(s)).strip(" ,")
    return s


def consolidate_pa(clinic):
    return PA_CONSOLIDATE.get(clinic, clinic)


def normalize_state(v):
    if pd.isna(v): return ""
    return str(v).strip().upper()


def load_ct():
    src = latest_csv(CT_DIR)
    if not src:
        print(f"[WARN] No CT CSV found in {CT_DIR}")
        return pd.DataFrame()
    print(f"[INFO] Loading CT: {os.path.basename(src)}")
    df = pd.read_csv(src, dtype={"PatNum": str}, low_memory=False)

    for col, _ in AGING_COLS:
        if col in df.columns:
            df[col] = df[col].map(parse_money)
        else:
            df[col] = 0.0
    df["BalTotal"] = df["BalTotal"].map(parse_money)

    # Use real Clinic if the export has one; fall back to City-proxy for older formats.
    if "Clinic" not in df.columns or df["Clinic"].fillna("").astype(str).str.strip().eq("").all():
        df["Clinic"] = df["City"].fillna("").astype(str).str.strip().str.title().replace("", "Unknown")
    else:
        df["Clinic"] = df["Clinic"].fillna("").astype(str).str.strip().replace("", "Unknown")

    if "Clinic_state" in df.columns:
        df["Clinic_state"] = df["Clinic_state"].map(normalize_state)
    else:
        df["Clinic_state"] = "CT"
    # If state col existed but rows aren't tagged CT (e.g. spacer rows), keep them out
    df = df[df.apply(is_real_row, axis=1)].copy()
    df = df[df["Clinic_state"] == "CT"].copy()
    df = df[df["BalTotal"] < 0].copy()

    df["Guarantor"] = df["Guarantor"].map(clean_guarantor)
    df["LastApptDate"] = df["LastApptDate"].map(parse_date)
    df["NextSchedAppt"] = df["NextSchedAppt"].map(parse_date)
    return df


def load_njpa():
    src = latest_csv(NJPA_DIR)
    if not src:
        print(f"[WARN] No NJ/PA CSV found in {NJPA_DIR}")
        return pd.DataFrame()
    print(f"[INFO] Loading NJ/PA: {os.path.basename(src)}")
    df = pd.read_csv(src, dtype={"PatNum": str}, low_memory=False)

    # Drop footer / garbage rows (TOTALS, spacer, non-numeric PatNum, foreign states)
    df["Clinic_state"] = df["Clinic_state"].map(normalize_state)
    df = df[df.apply(is_real_row, axis=1)].copy()
    df = df[df["Clinic_state"].isin(["PA", "NJ"])].copy()
    df = df[~df["Clinic"].isin(DROP_CLINIC)].copy()

    # Parse all aging cols
    for col, _ in AGING_COLS:
        df[col] = df[col].map(parse_money)
    df["BalTotal"] = df["BalTotal"].map(parse_money)

    # Only true credits (negative BalTotal)
    df = df[df["BalTotal"] < 0].copy()

    # Consolidate PA clinics
    pa = df["Clinic_state"] == "PA"
    df.loc[pa, "Clinic"] = df.loc[pa, "Clinic"].map(consolidate_pa)

    df["Guarantor"] = df["Guarantor"].map(clean_guarantor)
    df["LastApptDate"] = df["LastApptDate"].map(parse_date)
    df["NextSchedAppt"] = df["NextSchedAppt"].map(parse_date)

    return df


def oldest_bucket(row):
    """Return the (label, amount-in-that-display-bucket) of the oldest
    non-zero aging bucket (rightmost raw col = oldest)."""
    # walk raw cols oldest -> newest; sum the display bucket the oldest hit belongs to
    for col, label in reversed(RAW_TO_BUCKET):
        v = row.get(col, 0) or 0
        if abs(v) > 0.005:
            total = sum(row.get(c, 0) or 0 for c, lb in RAW_TO_BUCKET if lb == label)
            return label, total
    return "", 0.0


def to_records(df, state_filter):
    sub = df[df["Clinic_state"] == state_filter].copy()
    out = []
    for _, r in sub.iterrows():
        oldest_lbl, oldest_amt = oldest_bucket(r)
        rec = {
            "PatNum":       str(r.get("PatNum") or ""),
            "Clinic":       r.get("Clinic") or "",
            "State":        state_filter,
            "LastAppt":     r.get("LastApptDate") or "",
            "NextAppt":     r.get("NextSchedAppt") or "",
            "BalTotal":     round(float(r.get("BalTotal") or 0), 2),
            "OldestBucket": oldest_lbl,
            "OldestAmt":    round(float(oldest_amt or 0), 2),
        }
        for b in BUCKET_ORDER:
            rec[f"Bal_{b}"] = round(sum(float(r.get(c) or 0) for c, lb in RAW_TO_BUCKET if lb == b), 2)
        out.append(rec)

    # Sort: oldest bucket DESC (5+ yrs first), then by abs(BalTotal) DESC
    bucket_rank = {b: i for i, b in enumerate(BUCKET_ORDER)}
    out.sort(key=lambda r: (-bucket_rank.get(r["OldestBucket"], -1), -abs(r["BalTotal"])))
    return out


def overview_metrics(records_by_state):
    """Per-state and overall aging totals, clinic top-list."""
    overall = {"buckets": {b: 0.0 for b in BUCKET_ORDER}, "total": 0.0, "count": 0}
    per_state = {}
    per_clinic = {}

    for state, recs in records_by_state.items():
        s = {"buckets": {b: 0.0 for b in BUCKET_ORDER}, "total": 0.0, "count": len(recs)}
        for r in recs:
            for b in BUCKET_ORDER:
                v = r.get(f"Bal_{b}", 0) or 0
                s["buckets"][b] += v
                overall["buckets"][b] += v
            s["total"] += r["BalTotal"]
            overall["total"] += r["BalTotal"]
            overall["count"] += 1

            ck = (state, r["Clinic"])
            d = per_clinic.setdefault(ck, {"state": state, "clinic": r["Clinic"], "count": 0, "total": 0.0, "buckets": {b: 0.0 for b in BUCKET_ORDER}})
            d["count"] += 1
            d["total"] += r["BalTotal"]
            for b in BUCKET_ORDER:
                d["buckets"][b] += r.get(f"Bal_{b}", 0) or 0
        # round
        s["buckets"] = {k: round(v, 2) for k, v in s["buckets"].items()}
        s["total"] = round(s["total"], 2)
        per_state[state] = s

    overall["buckets"] = {k: round(v, 2) for k, v in overall["buckets"].items()}
    overall["total"] = round(overall["total"], 2)

    clinic_list = []
    for d in per_clinic.values():
        d["total"] = round(d["total"], 2)
        d["buckets"] = {k: round(v, 2) for k, v in d["buckets"].items()}
        clinic_list.append(d)
    clinic_list.sort(key=lambda x: x["total"])  # most negative first

    return overall, per_state, clinic_list


def previous_snapshot():
    """If a prior snapshot exists, load it for MoM comparison."""
    snap_dir = os.path.join(ROOT, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    snaps = sorted(glob.glob(os.path.join(snap_dir, "snapshot_*.json")))
    if not snaps:
        return None
    with open(snaps[-1]) as f:
        return json.load(f)


def save_snapshot(payload):
    snap_dir = os.path.join(ROOT, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    out = os.path.join(snap_dir, f"snapshot_{today}.json")
    summary = {
        "as_of": today,
        "overall": payload["overview"]["overall"],
        "per_state": payload["overview"]["per_state"],
    }
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[INFO] Snapshot saved: {out}")


def build_payload():
    df = load_njpa()
    if df.empty:
        print("[FATAL] No data loaded.")
        sys.exit(1)

    pa = to_records(df, "PA")
    nj = to_records(df, "NJ")

    ct_df = load_ct()
    ct = to_records(ct_df, "CT") if not ct_df.empty else []

    overall, per_state, clinic_list = overview_metrics({"PA": pa, "NJ": nj, "CT": ct})
    prev = previous_snapshot()

    payload = {
        "asOf": datetime.now().strftime("%Y-%m-%d"),
        "buckets": BUCKET_ORDER,
        "states": {
            "PA": pa,
            "NJ": nj,
            "CT": ct,
        },
        "overview": {
            "overall": overall,
            "per_state": per_state,
            "clinics": clinic_list,
            "prev": prev,
        },
        "staff": {
            "PA": ["AB", "CM"],
            "NJ": ["JR", "MS"],
            "CT": ["AB", "CM"],  # CT uses PA AR staff
        },
        "actions": [
            "PPO Refund Requested",
            "Patient Refund Processed",
            "Patient Refund Requested",
            "Medicaid Refund Processed",
            "TX Pre-Payment",
        ],
        "statuses": ["In Progress", "Completed"],
    }

    save_snapshot(payload)
    return payload


def embed(payload):
    tpl = os.path.join(ROOT, "template.html")
    if not os.path.exists(tpl):
        print(f"[WARN] template.html not found at {tpl} — skipping embed.")
        return
    with open(tpl) as f:
        html = f.read()
    js = json.dumps(payload, separators=(",", ":"))
    html = html.replace("__DATA_PLACEHOLDER__", js)
    for out in ("dashboard.html", "index.html"):
        with open(os.path.join(ROOT, out), "w") as f:
            f.write(html)
    print(f"[INFO] Embedded {len(js):,} chars into dashboard.html + index.html")


def main():
    payload = build_payload()
    print(f"[INFO] PA rows: {len(payload['states']['PA'])}")
    print(f"[INFO] NJ rows: {len(payload['states']['NJ'])}")
    print(f"[INFO] CT rows: {len(payload['states']['CT'])}")
    print(f"[INFO] Overall total credits: ${payload['overview']['overall']['total']:,.2f}")
    print(f"[INFO] Buckets (overall): {payload['overview']['overall']['buckets']}")
    embed(payload)
    out_json = os.path.join(ROOT, "dashboard_data.json")
    with open(out_json, "w") as f:
        json.dump(payload, f)
    print(f"[INFO] JSON also saved: {out_json}")


if __name__ == "__main__":
    main()
