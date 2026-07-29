"""
Concentration Similarity Index (CSI) — Byrne et al. (2024), AMT 17, 5129-5146.

The CSI compares the PM2.5 concentration-time profiles of two sensors over
their common observation period. For each common timestamp the pair either
"agrees" (f = 1) or "disagrees" (f = 0), and the CSI is the mean of f:

    ratio = |C_B - C_A| / sqrt(C_A * C_B)

    if C_A or C_B > PM_LIM:   agree when ratio < C_LIM_UPPER   (strict)
    else:                     agree when ratio < C_LIM_LOWER   (lenient,
                                                near-clean air is noisy)

Constants (Byrne 2024, optimised on co-location data):
    PM_LIM = 15 ug/m3, C_LIM_UPPER = 0.2, C_LIM_LOWER = 0.7

Edge cases not addressed in the paper, handled here explicitly:
  * Negative values (possible after the Barkjohn correction at low PM /
    high RH) are clipped to 0 before the ratio is formed.
  * If the geometric mean is 0 (one or both values are 0) the ratio is
    undefined; the pair is scored as agreeing only when both values are 0.
Both cases are rare at daily resolution; `csi_pair` reports the count so
they can be checked.

Note: Byrne developed the limits on HOURLY averages. This project applies
them to DAILY means (justified by ~36% network hourly coverage); absolute
CSI values are therefore not directly comparable to the paper's.
"""
from itertools import combinations

import numpy as np
import pandas as pd

# Constants live in config.py so sensitivity tests change them in one place.
# NOTE: import each name separately and explicitly — an earlier version
# imported a misspelled name inside one try/except, which silently reverted
# ALL constants to the fallbacks and would have made config edits no-ops.
from src.config import CSI_PM_LIM, CSI_C_UPPER, CSI_C_LOWER
from src.config import MIN_COMMON_DAYS as CSI_MIN_COMMON_DAYS


def csi_pair(a, b,
             pm_lim=CSI_PM_LIM,
             c_upper=CSI_C_UPPER,
             c_lower=CSI_C_LOWER,
             return_details=False):
    """
    CSI between two aligned 1-D arrays/Series (NaNs allowed).

    Returns (csi, n_common); with return_details=True also a dict with the
    per-timestep agreement flags and edge-case counts.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError(f"length mismatch: {a.shape} vs {b.shape}")

    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    n = a.size
    if n == 0:
        return (np.nan, 0, {}) if return_details else (np.nan, 0)

    n_negative = int(((a < 0) | (b < 0)).sum())
    a = np.clip(a, 0, None)
    b = np.clip(b, 0, None)

    denom = np.sqrt(a * b)
    zero_denom = denom == 0
    n_zero_denom = int(zero_denom.sum())

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.abs(b - a) / denom

    high = (a > pm_lim) | (b > pm_lim)          # strict regime
    f = np.where(high, ratio < c_upper, ratio < c_lower)
    # undefined ratio: agree only if both values are exactly 0
    f = np.where(zero_denom, (a == 0) & (b == 0), f)

    csi = float(f.mean())
    if return_details:
        return csi, n, {"f": f.astype(int),
                        "n_negative_clipped": n_negative,
                        "n_zero_denominator": n_zero_denom}
    return csi, n


def csi_matrix(daily_matrix, min_common=CSI_MIN_COMMON_DAYS, **limits):
    """
    Pairwise CSI for every column pair of a (days x sensors) DataFrame.

    Pairs with fewer than `min_common` overlapping non-NaN days are left
    as NaN — too little overlap to judge similarity. Extra keyword
    arguments (pm_lim, c_upper, c_lower) pass through to csi_pair for
    sensitivity testing.

    Returns
    -------
    csi     : DataFrame (sensors x sensors), diagonal = 1.0
    ncommon : DataFrame of common-day counts per pair
    """
    cols = list(daily_matrix.columns)
    k = len(cols)
    csi = pd.DataFrame(np.eye(k), index=cols, columns=cols)
    ncommon = pd.DataFrame(0, index=cols, columns=cols, dtype=int)

    values = {c: daily_matrix[c].to_numpy(dtype=float) for c in cols}
    for i, j in combinations(range(k), 2):
        ci, cj = cols[i], cols[j]
        score, n = csi_pair(values[ci], values[cj], **limits)
        ncommon.loc[ci, cj] = ncommon.loc[cj, ci] = n
        if n < min_common:
            score = np.nan
        csi.loc[ci, cj] = csi.loc[cj, ci] = score

    own_days = daily_matrix.notna().sum()
    for c in cols:
        ncommon.loc[c, c] = int(own_days[c])
    return csi, ncommon


def sensor_ranking(csi, ncommon):
    """
    Per-sensor summary of similarity to the rest of the network:
    mean off-diagonal CSI, number of valid pairs, median overlap days.
    Sorted ascending — least similar (fault candidates) first.
    """
    mask = ~np.eye(len(csi), dtype=bool)
    off_csi = csi.where(mask)
    off_n = ncommon.where(mask)
    rank = pd.DataFrame({
        "mean_csi": off_csi.mean(axis=1).round(3),
        "n_pairs": off_csi.notna().sum(axis=1).astype(int),
        "median_overlap_days": off_n.median(axis=1).round(0),
    })
    return rank.sort_values("mean_csi")