"""
PM2.5 quality flagging (Byrne et al. 2023) and humidity correction
(Barkjohn et al. 2021). Single source for both, so notebooks and batch
runs use identical definitions.
"""
import numpy as np
import pandas as pd

from src.config import (PM_A, PM_B, RH_COL,
                        MAX_PLAUSIBLE, PM_BREAK, REL_HIGH, REL_LOW)


def clean_sensor(df):
    """Add quality flags to a sensor's data. Keeps all rows; flags bad ones.

    Returns (flagged_dataframe, n_duplicate_rows_removed).
    """
    df = df.copy()

    # step 1 — drop fully-duplicate rows
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    n_dups = before - len(df)

    a, b = df[PM_A], df[PM_B]

    # step 2 — implausible-value flag (either channel out of range)
    df["flag_implausible"] = (a > MAX_PLAUSIBLE) | (b > MAX_PLAUSIBLE)

    # step 3 — two-step A/B agreement flag (Byrne 2023)
    mean_ab  = (a + b) / 2
    rel_diff = (a - b).abs() / mean_ab.replace(0, np.nan)   # avoid /0
    higher   = np.maximum(a, b)

    df["flag_ab"] = np.where(
        higher > PM_BREAK,
        rel_diff > REL_HIGH,      # strict band at high concentrations
        rel_diff > REL_LOW,       # lenient band at low concentrations
    )
    df["flag_ab"] = df["flag_ab"].fillna(False)

    # overall marker: clean only if nothing flagged it
    df["is_clean"] = ~(df["flag_implausible"] | df["flag_ab"])

    return df, n_dups


# --------------------------------------------------------------------------
# Humidity correction (Barkjohn et al. 2021), applied to the CF=ATM channel
# following Giordano et al. (2021).
# --------------------------------------------------------------------------
BARKJOHN_A  = 0.524
BARKJOHN_RH = -0.0862
BARKJOHN_C  = 5.75


def apply_humidity_correction(df, pm_col=PM_A, rh_col=RH_COL):
    """Barkjohn-corrected PM2.5 as a Series.

    RH is in percent. Floored at 0 (PM can't be negative);
    NaN where RH is missing (no correction possible).
    """
    corrected = BARKJOHN_A * df[pm_col] + BARKJOHN_RH * df[rh_col] + BARKJOHN_C
    return corrected.clip(lower=0).where(df[rh_col].notna())