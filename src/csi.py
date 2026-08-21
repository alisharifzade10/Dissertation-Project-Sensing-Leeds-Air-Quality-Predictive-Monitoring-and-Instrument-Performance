"""
Concentration Similarity Index — Byrne et al. (2024), AMT 17, 5129-5146.

For each pair of daily-mean PM2.5 values:
    ratio = |C_B - C_A| / sqrt(C_A * C_B)
    agree  = ratio < C_UPPER  if either value > PM_LIM  (strict regime)
           = ratio < C_LOWER  otherwise                  (lenient regime)
    CSI    = fraction of timesteps where the pair agrees

Edge cases: negatives are clipped to 0 before the ratio; if the geometric
mean is 0 the pair agrees only when both values are exactly 0.
"""
from itertools import combinations

import numpy as np
import pandas as pd

from src.config import CSI_PM_LIM, CSI_C_UPPER, CSI_C_LOWER
from src.config import MIN_COMMON_DAYS as CSI_MIN_COMMON_DAYS


def csi_pair(a, b,
             pm_lim=CSI_PM_LIM, c_upper=CSI_C_UPPER, c_lower=CSI_C_LOWER,
             return_details=False):
    """CSI between two aligned arrays/Series (NaNs allowed).

    Returns (csi, n_common); with return_details=True also a dict with
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

    denom      = np.sqrt(a * b)
    zero_denom = denom == 0
    n_zero_denom = int(zero_denom.sum())

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.abs(b - a) / denom

    high = (a > pm_lim) | (b > pm_lim)
    f = np.where(high, ratio < c_upper, ratio < c_lower)
    f = np.where(zero_denom, (a == 0) & (b == 0), f)

    csi = float(f.mean())
    if return_details:
        return csi, n, {"f": f.astype(int),
                        "n_negative_clipped": n_negative,
                        "n_zero_denominator": n_zero_denom}
    return csi, n


def csi_matrix(daily_matrix, min_common=CSI_MIN_COMMON_DAYS, **limits):
    """Pairwise CSI for every column pair of a (days × sensors) DataFrame.

    Pairs with fewer than `min_common` overlapping days are left as NaN.
    Returns (csi_df, ncommon_df).
    """
    cols = list(daily_matrix.columns)
    k    = len(cols)
    csi     = pd.DataFrame(np.eye(k), index=cols, columns=cols)
    ncommon = pd.DataFrame(0, index=cols, columns=cols, dtype=int)

    values = {c: daily_matrix[c].to_numpy(dtype=float) for c in cols}
    for i, j in combinations(range(k), 2):
        ci, cj  = cols[i], cols[j]
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
    """Mean off-diagonal CSI per sensor, sorted ascending (worst first)."""
    mask    = ~np.eye(len(csi), dtype=bool)
    off_csi = csi.where(mask)
    off_n   = ncommon.where(mask)
    rank = pd.DataFrame({
        "mean_csi":            off_csi.mean(axis=1).round(3),
        "n_pairs":             off_csi.notna().sum(axis=1).astype(int),
        "median_overlap_days": off_n.median(axis=1).round(0),
    })
    return rank.sort_values("mean_csi")


def mean_csi_against(series, matrix, exclude=None, min_common=CSI_MIN_COMMON_DAYS,
                     **limits):
    """Mean CSI of one daily series against every column of `matrix`.

    Used wherever a single series has to be scored against the network without
    rebuilding the whole pairwise matrix: the harmonisation test and the
    synthetic fault injection in notebook 08. Pairs with fewer than
    `min_common` overlapping days are skipped, exactly as in csi_matrix, so
    the number returned is on the same scale as the notebook 05 ranking.

    Returns (mean_csi, n_pairs).
    """
    scores = []
    for c in matrix.columns:
        if exclude is not None and c == exclude:
            continue
        pair = pd.concat([series, matrix[c]], axis=1).dropna()
        if len(pair) < min_common:
            continue
        score, _ = csi_pair(pair.iloc[:, 0].to_numpy(),
                            pair.iloc[:, 1].to_numpy(), **limits)
        scores.append(score)
    if not scores:
        return np.nan, 0
    return float(np.mean(scores)), len(scores)