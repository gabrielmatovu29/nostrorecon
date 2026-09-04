from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.conf import settings

import pandas as pd
import io
from difflib import SequenceMatcher


# ============================================================
# FILE LOCATIONS
# ============================================================

NOSTRO_FILE = settings.BASE_DIR / "data" / "nostros.xlsx"
LEDGER_FILE = settings.BASE_DIR / "data" / "ledgers.xlsx"


# ============================================================
# SYSTEM SETTINGS
# ============================================================

# ============================================================
# SYSTEM SETTINGS (RELAXED FOR AUTO-MATCHING)
# ============================================================

AUTO_MATCH_THRESHOLD = 100      # Lowered from 90 to auto-match items scoring 60+
REVIEW_THRESHOLD = 40          # Lowered from 60
CANDIDATE_THRESHOLD = 30       # Lowered from 50

# Rebalanced weights prioritizing Amount, Reference, and Direction
AMOUNT_WEIGHT = 0.45
DIRECTION_WEIGHT = 0.20
REFERENCE_WEIGHT = 0.25
COUNTERPARTY_WEIGHT = 0.10
CONTEXT_WEIGHT = 0.00
DATE_WEIGHT = 0.00


# ============================================================
# DATA LOADING
# ============================================================

def load_nostro_data():
    """Load and clean Nostro statement data."""

    df = pd.read_excel(NOSTRO_FILE)

    if "value_date" in df.columns:
        df["value_date"] = pd.to_datetime(
            df["value_date"],
            errors="coerce",
            format="mixed"
    )

    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(
            df["amount"],
            errors="coerce"
        ).fillna(0)

    text_columns = [
        "currency",
        "dc_indicator",
        "transaction_code",
        "reference",
        "related_account",
        "ordering_party",
        "description",
        "transaction_reference",
        "account_id",
        "statement_number",
        "sequence_number",
        "source_message_type",
        "sender",
        "receiver",
        "correspondent",
    ]

    for col in text_columns:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    return df


def load_ledger_data():
    """Load and clean Ledger data."""

    df = pd.read_excel(LEDGER_FILE)

    for col in ["operating_date", "value_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(
                df[col],
                errors="coerce",
                format="mixed"
        )

        df[col] = df[col].apply(
            lambda x: x.date() if pd.notna(x) else None
        )

    for col in ["debit", "credit"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            ).fillna(0)

    text_columns = [
        "account",
        "reference",
        "description",
        "rel_ref",
    ]

    for col in text_columns:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    return df


# ============================================================
# DISPLAY HELPERS
# ============================================================

def format_date(value):
    """Convert a pandas date to a readable string."""

    if pd.isna(value):
        return ""

    try:
        return pd.to_datetime(value).strftime("%d-%b-%Y")
    except Exception:
        return str(value)


def prepare_dataframe_for_display(df):
    """Prepare dataframe values for HTML display."""

    display_df = df.copy()

    for col in display_df.columns:
        if pd.api.types.is_datetime64_any_dtype(
            display_df[col]
        ):
            display_df[col] = display_df[col].dt.strftime(
                "%d-%b-%Y"
            )

    display_df = display_df.fillna("")

    return display_df


# ============================================================
# TEXT UTILITIES
# ============================================================

def normalize_text(value):
    """Normalize text before comparison."""

    if pd.isna(value):
        return ""

    value = str(value).upper().strip()

    for char in [",", ".", "/", "-", "_", ":", ";"]:
        value = value.replace(char, " ")

    value = " ".join(value.split())

    return value


def text_similarity(value1, value2):
    """Return similarity between two text values as percentage."""

    value1 = normalize_text(value1)
    value2 = normalize_text(value2)

    if not value1 or not value2:
        return 0

    if value1 == value2:
        return 100

    return round(
        SequenceMatcher(
            None,
            value1,
            value2
        ).ratio() * 100,
        2
    )


# ============================================================
# LEDGER DIRECTION
# ============================================================

def ledger_direction(row):
    """
    Determine whether the ledger transaction is a debit or credit.

    Assumption:
        Credit > 0 → CREDIT
        Debit > 0  → DEBIT
    """

    debit = float(row.get("debit", 0) or 0)
    credit = float(row.get("credit", 0) or 0)

    if credit > 0 and debit == 0:
        return "CREDIT"

    if debit > 0 and credit == 0:
        return "DEBIT"

    if credit > debit:
        return "CREDIT"

    if debit > credit:
        return "DEBIT"

    return ""


# ============================================================
# MATCHING COMPONENTS
# ============================================================

def amount_score(nostro_amount, ledger_amount):
    """Score based on amount similarity."""

    try:
        nostro_amount = abs(float(nostro_amount))
        ledger_amount = abs(float(ledger_amount))
    except (ValueError, TypeError):
        return 0

    difference = abs(
        nostro_amount - ledger_amount
    )

    if round(difference, 2) == 0:
        return 100

    if difference <= 1:
        return 95

    if difference <= 5:
        return 85

    if difference <= max(
        10,
        nostro_amount * 0.0001
    ):
        return 70

    if difference <= max(
        25,
        nostro_amount * 0.0005
    ):
        return 40

    return 0


def reference_score(nostro_row, ledger_row):
    """Compare Nostro and Ledger references."""

    nostro_references = [
        nostro_row.get("reference", ""),
        nostro_row.get("transaction_reference", ""),
        nostro_row.get("related_account", ""),
    ]

    ledger_references = [
        ledger_row.get("reference", ""),
        ledger_row.get("rel_ref", ""),
    ]

    best_score = 0

    for nostro_ref in nostro_references:

        nostro_ref = normalize_text(nostro_ref)

        if not nostro_ref:
            continue

        for ledger_ref in ledger_references:

            ledger_ref = normalize_text(ledger_ref)

            if not ledger_ref:
                continue

            if nostro_ref == ledger_ref:
                best_score = max(
                    best_score,
                    100
                )

            elif (
                nostro_ref in ledger_ref
                or ledger_ref in nostro_ref
            ):
                best_score = max(
                    best_score,
                    90
                )

            else:
                similarity = text_similarity(
                    nostro_ref,
                    ledger_ref
                )

                if similarity >= 70:
                    best_score = max(
                        best_score,
                        similarity
                    )

    return best_score


def direction_score(nostro_row, ledger_row):
    """
    Compare MT950 D/C indicator with ledger direction.

    Assumption:
        MT950 C = Ledger CREDIT
        MT950 D = Ledger DEBIT
    """

    nostro_dc = normalize_text(
        nostro_row.get("dc_indicator", "")
    )

    ledger_dc = ledger_direction(
        ledger_row
    )

    if not nostro_dc or not ledger_dc:
        return 0

    if (
        nostro_dc.startswith("C")
        and ledger_dc == "CREDIT"
    ):
        return 100

    if (
        nostro_dc.startswith("D")
        and ledger_dc == "DEBIT"
    ):
        return 100

    return 0


def date_score(nostro_date, ledger_date):
    nostro_date = pd.Timestamp(nostro_date)#Change
    ledger_date = pd.Timestamp(ledger_date)
    if pd.isna(nostro_date) or pd.isna(ledger_date):
        return 0

    # Convert both values to pandas timestamps
    nostro_date = pd.Timestamp(nostro_date)
    ledger_date = pd.Timestamp(ledger_date)
   
    days = abs((nostro_date - ledger_date).days)

    if days == 0:
        return 100

    elif days == 1:
        return 80

    elif days == 2:
        return 60

    elif days <= 5:
        return 30

    else:
        return 0


def counterparty_score(nostro_row, ledger_row):
    """
    Compare Nostro ordering party/description
    against Ledger description/account.
    """

    nostro_values = [
        nostro_row.get(
            "ordering_party",
            ""
        ),
        nostro_row.get(
            "description",
            ""
        ),
    ]

    ledger_values = [
        ledger_row.get(
            "description",
            ""
        ),
        ledger_row.get(
            "account",
            ""
        ),
    ]

    best_score = 0

    for nostro_value in nostro_values:

        nostro_value = normalize_text(
            nostro_value
        )

        if not nostro_value:
            continue

        for ledger_value in ledger_values:

            ledger_value = normalize_text(
                ledger_value
            )

            if not ledger_value:
                continue

            similarity = text_similarity(
                nostro_value,
                ledger_value
            )

            best_score = max(
                best_score,
                similarity
            )

    return best_score


def transaction_context_score(
    nostro_row,
    ledger_row
):
    """
    Compare transaction context.

    Current Ledger source does not contain
    MT950 transaction code.
    """

    nostro_code = normalize_text(
        nostro_row.get(
            "transaction_code",
            ""
        )
    )

    nostro_description = normalize_text(
        nostro_row.get(
            "description",
            ""
        )
    )

    ledger_description = normalize_text(
        ledger_row.get(
            "description",
            ""
        )
    )

    # Interest
    if "INTEREST" in nostro_description:

        if "INTEREST" in ledger_description:
            return 100

        return 0

    # NTRF
    if nostro_code == "NTRF":

        if (
            "TRANSFER" in ledger_description
            or "NTRF" in ledger_description
        ):
            return 90

    return 0


# ============================================================
# OVERALL MATCH SCORE
# ============================================================

def calculate_match_score(nostro_row, ledger_row):
    """Calculate weighted reconciliation score ignoring date."""

    ledger_dc = ledger_direction(ledger_row)
    ledger_amount = ledger_row.get("credit", 0) if ledger_dc == "CREDIT" else ledger_row.get("debit", 0)

    scores = {
        "amount": amount_score(
            nostro_row.get("amount", 0),
            ledger_amount
        ),
        "direction": direction_score(
            nostro_row,
            ledger_row
        ),
        "reference": reference_score(
            nostro_row,
            ledger_row
        ),
        "counterparty": counterparty_score(
            nostro_row,
            ledger_row
        ),
        "context": transaction_context_score(
            nostro_row,
            ledger_row
        ),
        "date": 0,
    }

    total = (
        scores["amount"] * AMOUNT_WEIGHT
        + scores["direction"] * DIRECTION_WEIGHT
        + scores["reference"] * REFERENCE_WEIGHT
        + scores["counterparty"] * COUNTERPARTY_WEIGHT
        + scores["context"] * CONTEXT_WEIGHT
    )

    return round(total, 2), scores

# ============================================================
# MATCH REASON
# ============================================================

def match_reason(scores):
    reasons = []

    if scores["amount"] >= 95:
        reasons.append("Exact amount")
    elif scores["amount"] >= 70:
        reasons.append("Close amount")

    if scores["direction"] == 100:
        reasons.append("Direction agrees")

    if scores["reference"] >= 90:
        reasons.append("Reference agrees")
    elif scores["reference"] >= 70:
        reasons.append("Similar reference")

    if scores["counterparty"] >= 80:
        reasons.append("Counterparty/description agrees")

    if scores["context"] >= 90:
        reasons.append("Transaction context agrees")

    if not reasons:
        return "Weak potential match"

    return ", ".join(reasons)

# ============================================================
# FIND CANDIDATES
# ============================================================

def find_candidates(
    nostro_row,
    ledger_df,
    reserved_ledger_indices
):
    """Find potential Ledger matches without date restrictions."""

    candidates = []

    nostro_amount = abs(
        float(
            nostro_row.get(
                "amount",
                0
            ) or 0
        )
    )

    for ledger_index, ledger_row in ledger_df.iterrows():

        if ledger_index in reserved_ledger_indices:
            continue

        # Determine Ledger amount
        ledger_direction_value = ledger_direction(ledger_row)

        if ledger_direction_value == "CREDIT":
            ledger_amount = abs(
                float(
                    ledger_row.get("credit", 0) or 0
                )
            )
        else:
            ledger_amount = abs(
                float(
                    ledger_row.get("debit", 0) or 0
                )
            )

        # Amount pre-filter (Allows up to 5% or fixed 500 difference)
        amount_difference = abs(nostro_amount - ledger_amount)
        amount_tolerance = max(500, nostro_amount * 0.05)

        if amount_difference > amount_tolerance:
            continue

        # Calculate score (Date check completely removed)
        score, breakdown = calculate_match_score(
            nostro_row,
            ledger_row
        )

        if score < CANDIDATE_THRESHOLD:
            continue

        candidates.append({
            "ledger_index": ledger_index,
            "ledger_id": ledger_row.get("ledger_id", ledger_index),
            "amount": ledger_amount,
            "value_date": ledger_row.get("value_date"),
            "description": ledger_row.get("description", ""),
            "reference": ledger_row.get("reference", ""),
            "score": score,
            "score_breakdown": breakdown,
            "reason": match_reason(breakdown),
        })

    candidates.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return candidates
# ============================================================
# HOME / DASHBOARD
# ============================================================

def home(request):

    nostro_df = load_nostro_data()
    ledger_df = load_ledger_data()

    nostro_count = len(
        nostro_df
    )

    ledger_count = len(
        ledger_df
    )

    manual_matches = request.session.get(
        "manual_matches",
        {}
    )

    reconciliation = run_matching(
        nostro_df,
        ledger_df,
        manual_matches
    )

    matched_count = len(
        reconciliation["matched_items"]
    )

    review_count = len(
        reconciliation["review_matches"]
    )

    unmatched_count = len(
        reconciliation["unmatched"]
    )

    if nostro_count > 0:

        match_rate = round(
            (
                matched_count
                / nostro_count
            ) * 100,
            2
        )

    else:

        match_rate = 0

    context = {

        "nostro_count":
            nostro_count,

        "ledger_count":
            ledger_count,

        "matched_count":
            matched_count,

        "review_count":
            review_count,

        "unmatched_count":
            unmatched_count,

        "match_rate":
            match_rate,
    }

    return render(
        request,
        "home/home.html",
        context
    )


# ============================================================
# NOSTRO PAGE
# ============================================================

def nostros(request):

    df = load_nostro_data()

    nostros = df.to_dict("records")

    return render(
        request,
        "home/nostros.html",
        {
            "nostros": nostros,
        }
    )



# ============================================================
# LEDGER PAGE
# ============================================================
def ledgers(request):
    
    df = load_ledger_data()

    ledgers = df.to_dict("records")

    return render(
        request,
        "home/ledgers.html",
        {
            "ledgers": ledgers,
        }
    )

# ============================================================
# RUN MATCHING ENGINE
# ============================================================

def run_matching(
    nostro_df,
    ledger_df,
    manual_matches=None
):

    if manual_matches is None:
        manual_matches = {}

    matched_items = []
    review_matches = []
    unmatched = []

    reserved_ledger_indices = set()

    manually_matched_nostros = set()

    # --------------------------------------------------------
    # PROCESS MANUAL MATCHES FIRST
    # --------------------------------------------------------

    for nostro_index, ledger_index in manual_matches.items():

        try:

            nostro_index = int(
                nostro_index
            )

            ledger_index = int(
                ledger_index
            )

        except (
            ValueError,
            TypeError
        ):

            continue

        if (
            nostro_index not in nostro_df.index
            or ledger_index not in ledger_df.index
        ):
            continue

        nostro_row = nostro_df.loc[
            nostro_index
        ]

        ledger_row = ledger_df.loc[
            ledger_index
        ]

        score, breakdown = calculate_match_score(
            nostro_row,
            ledger_row
        )

        matched_items.append({

            "nostro_index":
                nostro_index,

            "ledger_index":
                ledger_index,

            "nostro_id":
                nostro_row.get(
                    "nostro_id",
                    nostro_index
                ),

            "ledger_id":
                ledger_row.get(
                    "ledger_id",
                    ledger_index
                ),

            "matching_id":
                f"MANUAL-{nostro_index:05d}",

            "score":
                score,

            "reason":
                "Manually matched",
        })

        manually_matched_nostros.add(
            nostro_index
        )

        reserved_ledger_indices.add(
            ledger_index
        )

    # --------------------------------------------------------
    # AUTOMATIC MATCHING
    # --------------------------------------------------------

    for nostro_index, nostro_row in nostro_df.iterrows():

        if nostro_index in manually_matched_nostros:
            continue

        candidates = find_candidates(
            nostro_row,
            ledger_df,
            reserved_ledger_indices
        )

        # ----------------------------------------------------
        # NO CANDIDATES
        # ----------------------------------------------------

        if not candidates:

            unmatched.append({

                "nostro_index":
                    nostro_index,

                "nostro_id":
                    nostro_row.get(
                        "nostro_id",
                        nostro_index
                    ),

                "amount":
                    nostro_row.get(
                        "amount",
                        0
                    ),

                "currency":
                    nostro_row.get(
                        "currency",
                        ""
                    ),

                "value_date":
                    format_date(
                        nostro_row.get(
                            "value_date"
                        )
                    ),

                "dc_indicator":
                    nostro_row.get(
                        "dc_indicator",
                        ""
                    ),

                "transaction_code":
                    nostro_row.get(
                        "transaction_code",
                        ""
                    ),

                "ordering_party":
                    nostro_row.get(
                        "ordering_party",
                        ""
                    ),

                "description":
                    nostro_row.get(
                        "description",
                        ""
                    ),

                "status":
                    "Unmatched",
            })

            continue

        best = candidates[0]

        second_best = (
            candidates[1]
            if len(candidates) > 1
            else None
        )

        # ----------------------------------------------------
        # CLEAR WINNER
        # ----------------------------------------------------

        clear_winner = (
            second_best is None
            or (
                best["score"]
                - second_best["score"]
                >= 5
            )
        )

# ----------------------------------------------------
        # AUTO MATCH (RELAXED)
        # ----------------------------------------------------

        # Simply check if the top candidate meets the auto-match score threshold
        if best["score"] >= AUTO_MATCH_THRESHOLD:

            ledger_index = best["ledger_index"]

            matched_items.append({
                "nostro_index": nostro_index,
                "ledger_index": ledger_index,
                "nostro_id": nostro_row.get("nostro_id", nostro_index),
                "ledger_id": best["ledger_id"],
                "matching_id": f"MATCH-{nostro_index:05d}",
                "score": best["score"],
                "reason": best["reason"],
            })

            reserved_ledger_indices.add(ledger_index)
            continue

        # ----------------------------------------------------
        # MANUAL REVIEW
        # ----------------------------------------------------

        if best["score"] >= REVIEW_THRESHOLD:

            review_matches.append({

                "nostro_index":
                    nostro_index,

                "nostro_id":
                    nostro_row.get(
                        "nostro_id",
                        nostro_index
                    ),

                "amount":
                    nostro_row.get(
                        "amount",
                        0
                    ),

                "currency":
                    nostro_row.get(
                        "currency",
                        ""
                    ),

                "value_date":
                    format_date(
                        nostro_row.get(
                            "value_date"
                        )
                    ),

                "dc_indicator":
                    nostro_row.get(
                        "dc_indicator",
                        ""
                    ),

                "transaction_code":
                    nostro_row.get(
                        "transaction_code",
                        ""
                    ),

                "reference":
                    nostro_row.get(
                        "reference",
                        ""
                    ),

                "ordering_party":
                    nostro_row.get(
                        "ordering_party",
                        ""
                    ),

                "description":
                    nostro_row.get(
                        "description",
                        ""
                    ),

                "possible_matches":
                    [
                        {
                            **candidate,
                            "value_date":
                                format_date(
                                    candidate[
                                        "value_date"
                                    ]
                                ),
                        }
                        for candidate
                        in candidates[:10]
                    ],
            })

            continue

        # ----------------------------------------------------
        # UNMATCHED
        # ----------------------------------------------------

        unmatched.append({

            "nostro_index":
                nostro_index,

            "nostro_id":
                nostro_row.get(
                    "nostro_id",
                    nostro_index
                ),

            "amount":
                nostro_row.get(
                    "amount",
                    0
                ),

            "currency":
                nostro_row.get(
                    "currency",
                    ""
                ),

            "value_date":
                format_date(
                    nostro_row.get(
                        "value_date"
                    )
                ),

            "dc_indicator":
                nostro_row.get(
                    "dc_indicator",
                    ""
                ),

            "transaction_code":
                nostro_row.get(
                    "transaction_code",
                    ""
                ),

            "ordering_party":
                nostro_row.get(
                    "ordering_party",
                    ""
                ),

            "description":
                nostro_row.get(
                    "description",
                    ""
                ),

            "status":
                "Unmatched",
        })

    return {

        "matched_items":
            matched_items,

        "review_matches":
            review_matches,

        "unmatched":
            unmatched,
    }


# ============================================================
# MATCHING PAGE
# ============================================================

def matching(request):

    nostro_df = load_nostro_data()
    ledger_df = load_ledger_data()

    manual_matches = request.session.get(
        "manual_matches",
        {}
    )

    # --------------------------------------------------------
    # COMPLETE MANUAL MATCH
    # --------------------------------------------------------

    if request.method == "POST":

        if "complete_match" in request.POST:

            nostro_index = request.POST.get(
                "nostro_index"
            )

            ledger_index = request.POST.get(
                "ledger_index"
            )

            if (
                nostro_index is not None
                and ledger_index is not None
            ):

                manual_matches[
                    str(nostro_index)
                ] = int(ledger_index)

                request.session[
                    "manual_matches"
                ] = manual_matches

                request.session.modified = True

            return redirect(
                "matching"
            )

    # --------------------------------------------------------
    # RUN RECONCILIATION
    # --------------------------------------------------------

    results = run_matching(
        nostro_df,
        ledger_df,
        manual_matches
    )

    context = {

        "matched_items":
            results["matched_items"],

        "review_matches":
            results["review_matches"],

        "unmatched":
            results["unmatched"],

        "matched_count":
            len(results["matched_items"]),

        "review_count":
            len(results["review_matches"]),

        "unmatched_count":
            len(results["unmatched"]),
    }

    return render(
        request,
        "home/matching.html",
        context
    )


# ============================================================
# SETTINGS PAGE
# ============================================================

def settings_view(request):

    context = {

        "nostro_file":
            NOSTRO_FILE.name,

        "ledger_file":
            LEDGER_FILE.name,

        "auto_threshold":
            AUTO_MATCH_THRESHOLD,

        "review_threshold":
            REVIEW_THRESHOLD,

        "candidate_threshold":
            CANDIDATE_THRESHOLD,
    }

    return render(
        request,
        "home/settings.html",
        context
    )


# ============================================================
# EXCEL DOWNLOAD HELPER
# ============================================================

def dataframe_to_excel_response(
    df,
    filename
):

    output = io.BytesIO()

    with pd.ExcelWriter(
        output,
        engine="openpyxl"
    ) as writer:

        df.to_excel(
            writer,
            index=False
        )

    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )

    response[
        "Content-Disposition"
    ] = (
        f'attachment; filename="{filename}"'
    )

    return response


# ============================================================
# DOWNLOAD MATCHED
# ============================================================

def download_matched(request):

    nostro_df = load_nostro_data()
    ledger_df = load_ledger_data()

    manual_matches = request.session.get(
        "manual_matches",
        {}
    )

    results = run_matching(
        nostro_df,
        ledger_df,
        manual_matches
    )

    rows = []

    for item in results["matched_items"]:

        nostro_row = nostro_df.loc[
            item["nostro_index"]
        ]

        ledger_row = ledger_df.loc[
            item["ledger_index"]
        ]

        rows.append({

            "matching_id":
                item["matching_id"],

            "nostro_id":
                item["nostro_id"],

            "ledger_id":
                item["ledger_id"],

            "nostro_date":
                nostro_row.get(
                    "value_date"
                ),

            "ledger_date":
                ledger_row.get(
                    "value_date"
                ),

            "amount":
                nostro_row.get(
                    "amount"
                ),

            "currency":
                nostro_row.get(
                    "currency"
                ),

            "dc_indicator":
                nostro_row.get(
                    "dc_indicator"
                ),

            "transaction_code":
                nostro_row.get(
                    "transaction_code"
                ),

            "nostro_reference":
                nostro_row.get(
                    "reference"
                ),

            "ledger_reference":
                ledger_row.get(
                    "reference"
                ),

            "nostro_description":
                nostro_row.get(
                    "description"
                ),

            "ledger_description":
                ledger_row.get(
                    "description"
                ),

            "score":
                item["score"],

            "reason":
                item["reason"],
        })

    return dataframe_to_excel_response(
        pd.DataFrame(rows),
        "matched_items.xlsx"
    )


# ============================================================
# DOWNLOAD REVIEW
# ============================================================

def download_review(request):

    nostro_df = load_nostro_data()
    ledger_df = load_ledger_data()

    manual_matches = request.session.get(
        "manual_matches",
        {}
    )

    results = run_matching(
        nostro_df,
        ledger_df,
        manual_matches
    )

    rows = []

    for item in results["review_matches"]:

        for candidate in item[
            "possible_matches"
        ]:

            rows.append({

                "nostro_id":
                    item["nostro_id"],

                "nostro_amount":
                    item["amount"],

                "currency":
                    item["currency"],

                "nostro_date":
                    item["value_date"],

                "dc_indicator":
                    item["dc_indicator"],

                "transaction_code":
                    item["transaction_code"],

                "nostro_reference":
                    item["reference"],

                "ordering_party":
                    item["ordering_party"],

                "nostro_description":
                    item["description"],

                "ledger_id":
                    candidate["ledger_id"],

                "ledger_amount":
                    candidate["amount"],

                "ledger_date":
                    candidate["value_date"],

                "ledger_reference":
                    candidate["reference"],

                "ledger_description":
                    candidate["description"],

                "score":
                    candidate["score"],

                "reason":
                    candidate["reason"],
            })

    return dataframe_to_excel_response(
        pd.DataFrame(rows),
        "review_matches.xlsx"
    )


# ============================================================
# DOWNLOAD UNMATCHED
# ============================================================

def download_unmatched(request):

    nostro_df = load_nostro_data()
    ledger_df = load_ledger_data()

    manual_matches = request.session.get(
        "manual_matches",
        {}
    )

    results = run_matching(
        nostro_df,
        ledger_df,
        manual_matches
    )

    rows = []

    for item in results["unmatched"]:

        rows.append({

            "nostro_id":
                item["nostro_id"],

            "amount":
                item["amount"],

            "currency":
                item["currency"],

            "value_date":
                item["value_date"],

            "dc_indicator":
                item["dc_indicator"],

            "transaction_code":
                item["transaction_code"],

            "ordering_party":
                item["ordering_party"],

            "description":
                item["description"],

            "status":
                item["status"],
        })

    return dataframe_to_excel_response(
        pd.DataFrame(rows),
        "unmatched_items.xlsx"
    )