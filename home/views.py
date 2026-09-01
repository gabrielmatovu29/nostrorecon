from django.shortcuts import render, redirect
from django.http import HttpResponse
import pandas as pd
from django.conf import settings
import uuid
import io

# Normalize headers
def normalize(df):
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df

# =========================================================
# HOME DASHBOARD
# =========================================================
def home(request):
    nostro_file = settings.BASE_DIR / "data" / "nostro_statement_entries.xlsx"
    ledger_file = settings.BASE_DIR / "data" / "ledger_entries.xlsx"

    try:
        nostro_df = pd.read_excel(nostro_file)
        ledger_df = pd.read_excel(ledger_file)
    except Exception:
        nostro_df = pd.DataFrame()
        ledger_df = pd.DataFrame()

    counts = {"Nostro": len(nostro_df), "Ledger": len(ledger_df)}

    context = {
        "nostro_count": counts["Nostro"],
        "ledger_count": counts["Ledger"],
    }
    return render(request, "home/home.html", context)

# =========================================================
# NOSTROS
# =========================================================
def nostros(request):
    file_path = settings.BASE_DIR / "data" / "nostro_statement_entries.xlsx"
    try:
        df = pd.read_excel(file_path)
    except Exception:
        df = pd.DataFrame()
    context = {"columns": df.columns, "data": df.values.tolist()}
    return render(request, "home/nostros.html", context)

# =========================================================
# LEDGERS
# =========================================================
def ledgers(request):
    file_path = settings.BASE_DIR / "data" / "ledger_entries.xlsx"
    try:
        df = pd.read_excel(file_path)
    except Exception:
        df = pd.DataFrame()
    context = {"columns": df.columns, "data": df.values.tolist()}
    return render(request, "home/ledgers.html", context)

# =========================================================
# MATCHING VIEW
# =========================================================
def matching(request):
    nostro_file = settings.BASE_DIR / "data" / "nostro_statement_entries.xlsx"
    ledger_file = settings.BASE_DIR / "data" / "ledger_entries.xlsx"

    nostro_df = normalize(pd.read_excel(nostro_file))
    ledger_df = normalize(pd.read_excel(ledger_file))

    print("Nostro columns:", nostro_df.columns)
    print("Ledger columns:", ledger_df.columns)

    # Ensure status/matching_id exist
    for df in [nostro_df, ledger_df]:
        if "status" not in df.columns:
            df["status"] = "Unmatched"
        if "matching_id" not in df.columns:
            df["matching_id"] = ""

    # Manual complete match
    if request.method == "POST" and "complete_match" in request.POST:
        nostro_index = int(request.POST.get("nostro_index"))
        ledger_index = int(request.POST.get("ledger_index"))
        match_id = "MATCH-" + uuid.uuid4().hex[:8].upper()
        nostro_df.loc[nostro_index, ["status", "matching_id"]] = ["Matched", match_id]
        ledger_df.loc[ledger_index, ["status", "matching_id"]] = ["Matched", match_id]
        nostro_df.to_excel(nostro_file, index=False)
        ledger_df.to_excel(ledger_file, index=False)
        return redirect("matching")

    # Auto‑matching
    for n_index, nostro in nostro_df.iterrows():
        if str(nostro["status"]).lower() == "matched":
            continue
        for l_index, ledger in ledger_df.iterrows():
            if str(ledger["status"]).lower() == "matched":
                continue
            # Amount check (absolute values)
            try:
                same_amount = (
                    abs(abs(float(nostro.get("amount", 0))) -
                        abs(float(ledger.get("amount", 0)))) < 0.01
                )
            except:
                same_amount = False
            # Value date tolerance ±2 days
            try:
                date_diff = abs(pd.to_datetime(nostro.get("value_date")) -
                                pd.to_datetime(ledger.get("value_date"))).days
                date_ok = date_diff <= 2
            except:
                date_ok = False
            # Transaction type rules
            nostro_type = str(nostro.get("type", "")).upper()
            ledger_type = str(ledger.get("type", "")).upper()
            tx_ok = (
                (nostro_type == "LD" and ledger_type == "SC") or
                (nostro_type == "LC" and ledger_type == "SD")
            )
            if same_amount and date_ok and tx_ok:
                match_id = "MATCH-" + uuid.uuid4().hex[:8].upper()
                nostro_df.loc[n_index, ["status", "matching_id"]] = ["Matched", match_id]
                ledger_df.loc[l_index, ["status", "matching_id"]] = ["Matched", match_id]
                break

    nostro_df.to_excel(nostro_file, index=False)
    ledger_df.to_excel(ledger_file, index=False)

    # Build context lists
    matched_items, review_matches, unmatched = [], [], []

    for n_index, nostro in nostro_df.iterrows():
        if str(nostro["status"]).lower() == "matched":
            match_id = nostro["matching_id"]
            ledger_match = ledger_df[ledger_df["matching_id"] == match_id]
            if not ledger_match.empty:
                ledger = ledger_match.iloc[0]
                matched_items.append({
                    "nostro_id": nostro.get("nostro_id"),
                    "ledger_id": ledger.get("ledger_id"),
                    "matching_id": match_id,
                })
        else:
            candidates = []
            for l_index, ledger in ledger_df.iterrows():
                if str(ledger["status"]).lower() == "matched":
                    continue
                try:
                    same_amount = (
                        abs(abs(float(nostro.get("amount", 0))) -
                            abs(float(ledger.get("amount", 0)))) < 0.01
                    )
                except:
                    same_amount = False
                try:
                    date_diff = abs(pd.to_datetime(nostro.get("value_date")) -
                                    pd.to_datetime(ledger.get("value_date"))).days
                    date_ok = date_diff <= 2
                except:
                    date_ok = False
                nostro_type = str(nostro.get("type", "")).upper()
                ledger_type = str(ledger.get("type", "")).upper()
                tx_ok = (
                    (nostro_type == "LD" and ledger_type == "SC") or
                    (nostro_type == "LC" and ledger_type == "SD")
                )
                if same_amount and date_ok and tx_ok:
                    candidates.append({
                        "ledger_index": l_index,
                        "ledger_id": ledger.get("ledger_id"),
                        "amount": ledger.get("amount"),
                        "currency": ledger.get("currency"),
                        "value_date": ledger.get("value_date"),
                    })
            if candidates:
                review_matches.append({
                    "nostro_index": n_index,
                    "nostro_id": nostro.get("nostro_id"),
                    "amount": nostro.get("amount"),
                    "currency": nostro.get("currency"),
                    "value_date": nostro.get("value_date"),
                    "possible_matches": candidates,
                })
            else:
                unmatched.append({
                    "nostro_index": n_index,
                    "nostro_id": nostro.get("nostro_id"),
                    "amount": nostro.get("amount"),
                    "currency": nostro.get("currency"),
                    "value_date": nostro.get("value_date"),
                    "status": nostro.get("status"),
                })

    print("Matched count:", len(matched_items))
    print("Review count:", len(review_matches))
    print("Unmatched count:", len(unmatched))

    context = {
        "matched_items": matched_items[:20],
        "review_matches": review_matches[:20],
        "unmatched": unmatched[:20],
    }
    return render(request, "home/matching.html", context)

# =========================================================
# DOWNLOAD ENDPOINTS
# =========================================================
# DOWNLOAD ENDPOINTS
# =========================================================
def download_matched(request):
    file_path = settings.BASE_DIR / "data" / "nostro_statement_entries.xlsx"
    df = normalize(pd.read_excel(file_path))
    matched = df[df["status"] == "Matched"]
    buffer = io.BytesIO()
    matched.to_excel(buffer, index=False)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.ms-excel")
    response["Content-Disposition"] = "attachment; filename=matched.xlsx"
    return response


def download_unmatched(request):
    file_path = settings.BASE_DIR / "data" / "nostro_statement_entries.xlsx"
    df = normalize(pd.read_excel(file_path))
    unmatched = df[df["status"] != "Matched"]
    buffer = io.BytesIO()
    unmatched.to_excel(buffer, index=False)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.ms-excel")
    response["Content-Disposition"] = "attachment; filename=unmatched.xlsx"
    return response


def download_review(request):
    file_path = settings.BASE_DIR / "data" / "nostro_statement_entries.xlsx"
    df = normalize(pd.read_excel(file_path))
    review = df[df["status"] == "Possible Match"]
    buffer = io.BytesIO()
    review.to_excel(buffer, index=False)
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type="application/vnd.ms-excel")
    response["Content-Disposition"] = "attachment; filename=review.xlsx"
    return response
