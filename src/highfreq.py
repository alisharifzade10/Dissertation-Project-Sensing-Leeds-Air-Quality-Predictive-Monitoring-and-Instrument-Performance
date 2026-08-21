"""
High-frequency local-source filter, following Byrne et al. (2023).

Byrne et al. work at the two-minute scale. They define DPM as the deviation of
each reading from the mean of the hour containing it, and use the standard
deviation of DPM within that hour, sigma_DPM, to mark hours dominated by
short-lived plumes from nearby combustion. Hours with a large sigma_DPM are
locally influenced; hours with a small one carry only the slower regional
signal.

DPM is a within-hour centring, so its standard deviation over an hour is just
the standard deviation of the readings in that hour. The filter therefore
reduces to a resample, and no explicit DPM series has to be built. Everything
below works from a per-sensor table of hourly mean, standard deviation and
count.

Two exposure fractions follow (their Sect. 3.4):
  A_F / A_T   share of total PM2.5 observed during locally influenced hours
  A_f / A_T   share of the total attributable to the excess above a background
              interpolated across each locally influenced episode
"""
import numpy as np
import pandas as pd

from src.config import (
    MIN_READ_PER_HOUR, SIGMA_DPM_THRESH, SIGMA_DPM_MAX_GAP, LOCAL_TZ,
    WINTER_MONTHS, SUMMER_MONTHS,
)


def hourly_stats(series, min_count=MIN_READ_PER_HOUR):
    """Hourly mean, standard deviation and count from a two-minute series.

    The standard deviation is sigma_DPM: the spread of the two-minute readings
    about their own hourly mean. Hours with fewer than min_count readings are
    dropped, using the same completeness rule as the rest of the pipeline.
    """
    agg = series.resample("h").agg(["mean", "std", "count"])
    return agg[agg["count"] >= min_count].dropna(subset=["mean", "std"])


def flag_local_hours(stats, thresh=SIGMA_DPM_THRESH):
    """Mark hours whose sigma_DPM exceeds the threshold."""
    return stats["std"] > thresh


def episode_background(mean_hourly, is_local, max_gap=SIGMA_DPM_MAX_GAP):
    """Background level during each locally influenced episode.

    Byrne et al. take the background as the level interpolated between the
    start and the end of each high-fluctuation period. Blanking the flagged
    hours and interpolating in time does exactly that, and leaves episodes at
    the very start or end of a record undefined rather than extrapolated.

    The series is put back onto a complete hourly index first, so that `limit`
    counts clock hours rather than surviving rows: a sensor that was off air
    for a week must not have a background drawn straight across the gap.
    """
    full = pd.date_range(mean_hourly.index.min(), mean_hourly.index.max(),
                         freq="h")
    blanked = mean_hourly.where(~is_local).reindex(full)
    filled = blanked.interpolate(method="time", limit=max_gap,
                                 limit_area="inside")
    return filled.reindex(mean_hourly.index)


def exposure_fractions(stats, thresh=SIGMA_DPM_THRESH):
    """Local-influence summary for one sensor.

    Returns time_local (share of valid hours flagged), af_at (share of total
    PM2.5 seen during those hours) and af_local_at (share of the total made up
    by the excess above the interpolated background). Each hour carries equal
    weight, so summing hourly means is the discrete form of the integral under
    the concentration-time profile.
    """
    if stats.empty:
        return {}

    is_local = flag_local_hours(stats, thresh)
    mean = stats["mean"]
    total = float(mean.sum())
    if total <= 0:
        return {}

    background = episode_background(mean, is_local)
    excess = (mean - background).clip(lower=0)

    return {
        "n_hours":     int(len(stats)),
        "time_local":  float(is_local.mean()),
        "af_at":       float(mean[is_local].sum() / total),
        "af_local_at": float(excess[is_local].sum() / total),
        "median_sigma": float(stats["std"].median()),
        "mean_pm":     float(mean.mean()),
    }


def seasonal_fractions(stats, thresh=SIGMA_DPM_THRESH, tz=LOCAL_TZ,
                       winter=WINTER_MONTHS, summer=SUMMER_MONTHS):
    """Local-influence fractions split into winter and summer.

    Solid-fuel burning is the source Byrne et al. identify, and it is strongly
    seasonal, so a genuine local source should show a much larger winter than
    summer fraction. An instrument fault has no reason to follow the heating
    season.
    """
    local_index = stats.index.tz_convert(tz)
    out = {}
    for label, months in (("winter", winter), ("summer", summer)):
        sub = stats[np.isin(local_index.month, months)]
        f = exposure_fractions(sub, thresh)
        if f:
            out[f"time_local_{label}"] = f["time_local"]
            out[f"af_at_{label}"] = f["af_at"]
            out[f"n_hours_{label}"] = f["n_hours"]
    if "time_local_winter" in out and "time_local_summer" in out:
        w, s = out["time_local_winter"], out["time_local_summer"]
        # A site that fluctuates in winter and not at all in summer is the
        # strongest seasonal signature there is, so the ratio is infinite
        # rather than undefined. It is only undefined when neither season
        # shows any local influence.
        if s > 0:
            out["winter_summer_ratio"] = w / s
        elif w > 0:
            out["winter_summer_ratio"] = np.inf
        else:
            out["winter_summer_ratio"] = np.nan
    return out


def diurnal_sigma(stats, tz=LOCAL_TZ):
    """Median sigma_DPM by local clock hour.

    Byrne et al. found the highest hourly standard deviation at 18:00 in
    December, matching domestic solid-fuel use. An evening peak here is the
    same signature; a flat profile is not.
    """
    local_index = stats.index.tz_convert(tz)
    return stats["std"].groupby(local_index.hour).median().reindex(range(24))


def excursion_structure(a, b, local_hours, min_count=MIN_READ_PER_HOUR):
    """What the fluctuation looks like up close, inside locally influenced hours.

    Two quantities, both computed only on the hours the sigma_DPM filter has
    flagged, and both aimed at the same question: are the excursions particles
    or electronics?

    lag1
        Median lag-1 autocorrelation of the two-minute readings within an
        hour. A plume drifting past a sensor takes minutes to arrive and
        minutes to clear, so consecutive readings are strongly related.
        Electronic noise is independent from one reading to the next and sits
        near zero however large it is.

    ab_corr, ab_flag_rate
        Agreement between the two Plantower counters during those same hours.
        The channels sample the same air a few centimetres apart, so real
        particles register on both at once; a failing detector moves one
        channel and not the other. This is the diagnostic the PA-II's dual
        design exists to support, and it is applied here to the RAW readings,
        because the cleaned record has already had disagreeing rows removed.
    """
    pm = (a + b) / 2
    hour = pm.index.floor("h")
    keep = hour.isin(local_hours)
    if not keep.any():
        return {}

    lag1 = []
    for _, grp in pm[keep].groupby(hour[keep]):
        v = grp.to_numpy()
        if len(v) >= min_count and v[:-1].std() > 0 and v[1:].std() > 0:
            lag1.append(float(np.corrcoef(v[:-1], v[1:])[0, 1]))

    ea, eb = a[keep], b[keep]
    both_vary = ea.std() > 0 and eb.std() > 0
    rel = (ea - eb).abs() / ((ea + eb) / 2).replace(0, np.nan)

    return {
        "n_local_hours": int(keep.sum()),
        "lag1":          float(np.median(lag1)) if lag1 else np.nan,
        "ab_corr":       float(ea.corr(eb)) if both_vary else np.nan,
        "ab_disagree":   float((rel > 0.5).mean()),
    }
