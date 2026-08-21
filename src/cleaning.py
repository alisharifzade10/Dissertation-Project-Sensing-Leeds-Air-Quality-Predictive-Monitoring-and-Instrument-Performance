"""
PM2.5 quality flags and the Barkjohn humidity correction.

Three independent flags are produced, all flag-not-delete:
  flag_implausible  either channel outside the sensor's operating range
  flag_ab           the two channels disagree      (Byrne et al. 2023)
  flag_flatline     both channels frozen on one value

The flatline flag exists because the A/B test has a blind spot: if a unit
stops updating, both channels report the same stale value and agree
perfectly, so a rule built on their difference sees nothing wrong.

Single source of truth, so notebooks and the loader use identical definitions.
"""
import numpy as np
import pandas as pd

from src.config import (
    PM_A, PM_B, RH_COL, MAX_PLAUSIBLE, PM_BREAK, REL_HIGH, REL_LOW,
    AB_ABS_MIN, AB_FLOOR_SWEEP, FLATLINE_RUN, FLATLINE_IGNORE_ZERO,
)

BARKJOHN_A  = 0.524
BARKJOHN_RH = -0.0862
BARKJOHN_C  = 5.75


def ab_flag(a, b, abs_min=AB_ABS_MIN,
            pm_break=PM_BREAK, rel_high=REL_HIGH, rel_low=REL_LOW):
    """Byrne et al. (2023) two-band A/B disagreement test, with an optional
    absolute floor on the difference.

    The relative difference is taken against the channel mean. Above
    `pm_break` the channels must agree within `rel_high`, at or below it
    within `rel_low`. With abs_min > 0 a row is only flagged if the absolute
    difference also exceeds abs_min, which stops counting noise in near-clean
    air being read as a fault. abs_min = 0 reproduces Byrne exactly.
    """
    mean_ab  = (a + b) / 2
    rel_diff = (a - b).abs() / mean_ab.replace(0, np.nan)
    higher   = np.maximum(a, b)

    rel_fail = pd.Series(
        np.where(higher > pm_break, rel_diff > rel_high, rel_diff > rel_low),
        index=a.index,
    ).fillna(False).astype(bool)

    if abs_min > 0:
        rel_fail &= (a - b).abs() > abs_min
    return rel_fail


def flatline_flag(a, b, min_run=FLATLINE_RUN, ignore_zero=FLATLINE_IGNORE_ZERO):
    """Flag readings inside a run of identical values on BOTH channels.

    Consecutive rows are grouped into runs of an unchanged (A, B) pair; any
    run at least `min_run` readings long is flagged. At 2-min spacing,
    min_run = 90 means three hours without either channel moving.

    With ignore_zero=True, runs sitting at exactly (0, 0) are not flagged. A
    PMS5003 in clean air reports zero legitimately, so a run of zeros is not
    evidence of frozen electronics, and flagging it would preferentially
    delete the cleanest readings in the network -- the ones that set the
    spatial baseline in notebook 07.
    """
    changed = (a.diff() != 0) | (b.diff() != 0)
    run_id  = changed.fillna(True).cumsum()
    run_len = run_id.map(run_id.value_counts())
    frozen  = run_len >= min_run
    if ignore_zero:
        frozen &= ~((a == 0) & (b == 0))
    return frozen.to_numpy()


def clean_sensor(df, abs_min=AB_ABS_MIN, flatline_run=FLATLINE_RUN,
                 flatline_ignore_zero=FLATLINE_IGNORE_ZERO):
    """Apply all three flags. Returns (flagged_df, n_duplicates_removed).

    A fourth column, flag_zero_run, records runs of identical zeros. It is a
    diagnostic only and does not enter is_clean; notebook 04 reports it so the
    decision to leave zero runs in the data is evidenced rather than assumed.
    """
    df = df.copy()
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    n_dups = before - len(df)

    a, b = df[PM_A], df[PM_B]

    df["flag_implausible"] = (a > MAX_PLAUSIBLE) | (b > MAX_PLAUSIBLE)
    df["flag_ab"]          = ab_flag(a, b, abs_min=abs_min)
    df["flag_flatline"]    = flatline_flag(a, b, min_run=flatline_run,
                                           ignore_zero=flatline_ignore_zero)
    df["flag_zero_run"]    = (flatline_flag(a, b, min_run=flatline_run,
                                            ignore_zero=False)
                              & ~df["flag_flatline"])

    df["is_clean"] = ~(df["flag_implausible"] | df["flag_ab"] | df["flag_flatline"])
    return df, n_dups


def ab_rule_sweep(df, floors=AB_FLOOR_SWEEP):
    """Flag rate under a range of absolute floors, split by concentration band.

    Used in notebook 04 to choose AB_ABS_MIN. The high band is the informative
    one: above 15 ug/m3 the 5% relative test is tight and the absolute floor
    changes little, so a floor that collapses the low-band rate while leaving
    the high-band rate intact is removing noise rather than signal.
    """
    a, b   = df[PM_A], df[PM_B]
    higher = np.maximum(a, b)
    high   = higher > PM_BREAK

    rows = []
    for f in floors:
        flag = ab_flag(a, b, abs_min=f)
        rows.append({
            "abs_floor_ugm3": f,
            "pct_flagged_all":  round(100 * flag.mean(), 1),
            "pct_flagged_low":  round(100 * flag[~high].mean(), 1) if (~high).any() else np.nan,
            "pct_flagged_high": round(100 * flag[high].mean(), 1) if high.any() else np.nan,
        })
    return pd.DataFrame(rows)


def apply_humidity_correction(df, pm_col=None, rh_col=RH_COL):
    """Barkjohn-corrected PM2.5. Default uses (A+B)/2, matching how the
    coefficients were fitted. Pass pm_col to correct a single channel for
    diagnostics. Returns NaN where RH is missing."""
    pa = (df[PM_A] + df[PM_B]) / 2 if pm_col is None else df[pm_col]
    corrected = BARKJOHN_A * pa + BARKJOHN_RH * df[rh_col] + BARKJOHN_C
    return corrected.clip(lower=0).where(df[rh_col].notna())