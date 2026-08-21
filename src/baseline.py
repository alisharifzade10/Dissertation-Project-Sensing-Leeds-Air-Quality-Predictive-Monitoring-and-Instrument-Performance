"""
Spatial baseline separation for the Leeds PurpleAir network.

Each sensor's hourly value is decomposed as C_i(t) = B(t) + I_i(t), a
regional background B shared by the network and a local increment I specific
to sensor i (Lenschow et al., 2001). Functions that estimate a per-sensor
quantity use a leave-one-out reference so the sensor under test never
contaminates the baseline it is measured against.
"""
import numpy as np
import pandas as pd

from src.config import (
    BASELINE_Q, MIN_SENSORS_PER_HOUR, MIN_SENSORS_FOR_BASELINE,
    LOCAL_TZ, NIGHT_HOURS, CSI_PM_LIM, N_NEIGHBOURS,
)


# --------------------------------------------------------------------------
# Baselines and references
# --------------------------------------------------------------------------
def network_baseline(hm, q=BASELINE_Q, min_sensors=MIN_SENSORS_FOR_BASELINE):
    """Spatial baseline: q-th quantile across sensors at each timestamp.
    NaN where fewer than min_sensors are reporting.

    The default is MIN_SENSORS_FOR_BASELINE, not MIN_SENSORS_PER_HOUR. A low
    quantile needs more sensors than a median does before it means anything:
    at n = 5 the 0.10 quantile is essentially the minimum, and the minimum is
    won by whichever sensor reads lowest, which is the fault being hunted."""
    return hm.quantile(q, axis=1).where(hm.notna().sum(axis=1) >= min_sensors)


def loo_baseline(hm, q=BASELINE_Q, min_sensors=MIN_SENSORS_FOR_BASELINE):
    """Leave-one-out spatial baseline: same shape as hm, column c built
    from all sensors except c."""
    out = {}
    for c in hm.columns:
        others = hm.drop(columns=c)
        out[c] = others.quantile(q, axis=1).where(
            others.notna().sum(axis=1) >= min_sensors)
    return pd.DataFrame(out, index=hm.index)


def loo_reference(hm, min_sensors=MIN_SENSORS_PER_HOUR):
    """Leave-one-out network median — what each sensor is regressed against
    in offset_gain."""
    out = {}
    for c in hm.columns:
        others = hm.drop(columns=c)
        out[c] = others.median(axis=1).where(
            others.notna().sum(axis=1) >= min_sensors)
    return pd.DataFrame(out, index=hm.index)


def local_increment(hm, baseline):
    """Concentration above baseline. baseline may be a Series (one baseline
    for the whole network) or a DataFrame of leave-one-out baselines.
    Negative values are kept — a sensor below the network background is a
    fault signature."""
    if isinstance(baseline, pd.DataFrame):
        return hm - baseline.reindex_like(hm)
    return hm.sub(baseline, axis=0)


# --------------------------------------------------------------------------
# Conditioning masks
# --------------------------------------------------------------------------
def night_mask(index, tz=LOCAL_TZ, hours=NIGHT_HOURS):
    """Boolean mask for local-clock night hours (inclusive)."""
    local = index.tz_convert(tz)
    lo, hi = hours
    return (local.hour >= lo) & (local.hour <= hi)


def well_mixed_mask(hm, baseline, max_spread=None, spread_q=0.5, relative=False):
    """Timestamps when the network is spatially uniform (small IQR across
    sensors). With relative=True the IQR is divided by the network median,
    which avoids the absolute cut selecting only clean hours. With
    max_spread=None the threshold is the spread_q quantile of observed spread.
    Returns (mask, threshold_used)."""
    spread = hm.quantile(0.75, axis=1) - hm.quantile(0.25, axis=1)
    if relative:
        med = hm.median(axis=1)
        spread = spread / med.where(med > 0.5)
    if max_spread is None:
        max_spread = spread.quantile(spread_q)
    return (spread <= max_spread) & baseline.notna(), float(max_spread)


# --------------------------------------------------------------------------
# Instrument bias
# --------------------------------------------------------------------------
def offset_gain(hm, tz=LOCAL_TZ, night_hours=None, n_bins=10,
                q=BASELINE_Q, min_sensors_baseline=MIN_SENSORS_FOR_BASELINE,
                min_sensors_ref=MIN_SENSORS_PER_HOUR,
                spread_q=0.5, relative_spread=True,
                min_hours=200, ref_ugm3=CSI_PM_LIM, loo=True):
    """Fit sensor = gain * reference + offset for each sensor using
    well-mixed hours. The reference is cut into n_bins quantile bins and the
    fit is to bin medians, making it robust to outliers.

    Returns a DataFrame with one row per sensor, sorted by bias_max.
    Columns: offset_ugm3, gain, fit_lo/hi, bias_lo/hi, bias_max, bias_ref,
    crossover (conc. where offset and gain cancel), n_hours, n_bins_used,
    r2_bins.

    r2_bins is the fit to the n_bins bin medians, not to the hourly data. It
    is close to 1 for almost every sensor because bin medians of a monotone
    relationship are nearly collinear by construction, so it says the linear
    form is adequate and nothing about how tightly the sensor tracks the
    network hour by hour.
    """
    base = network_baseline(hm, q=q, min_sensors=min_sensors_baseline)
    sel, used_spread = well_mixed_mask(hm, base, spread_q=spread_q,
                                       relative=relative_spread)
    if night_hours is not None:
        sel = sel & pd.Series(night_mask(hm.index, tz=tz, hours=night_hours),
                              index=hm.index)

    sub = hm.loc[sel]
    ref = (loo_reference(sub, min_sensors=min_sensors_ref) if loo else
           pd.DataFrame({c: sub.median(axis=1) for c in sub.columns},
                        index=sub.index))

    rows = {}
    for name in sub.columns:
        pair = pd.DataFrame({"net": ref[name], "sen": sub[name]}).dropna()
        if len(pair) < min_hours:
            continue
        bins = pd.qcut(pair["net"], n_bins, duplicates="drop")
        g = pair.groupby(bins, observed=True).median().dropna()
        if len(g) < 3:
            continue

        x, y = g["net"].to_numpy(), g["sen"].to_numpy()
        gain, offset = np.polyfit(x, y, 1)
        ss_res = float(((y - (gain * x + offset)) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        lo, hi = float(x.min()), float(x.max())
        b_lo, b_hi = offset + (gain - 1) * lo, offset + (gain - 1) * hi
        rows[name] = {
            "offset_ugm3": offset,
            "gain":        gain,
            "fit_lo":      lo,
            "fit_hi":      hi,
            "bias_lo":     b_lo,
            "bias_hi":     b_hi,
            "bias_max":    max(abs(b_lo), abs(b_hi)),
            "bias_ref":    offset + (gain - 1) * ref_ugm3,
            "crossover":   -offset / (gain - 1) if abs(gain - 1) > 0.02 else np.nan,
            "n_hours":     int(len(pair)),
            "n_bins_used": int(len(g)),
            "r2_bins":     1 - ss_res / ss_tot if ss_tot > 0 else np.nan,
        }

    out = pd.DataFrame(rows).T
    out.attrs.update(max_spread_used=used_spread, n_timestamps=int(sel.sum()),
                     relative_spread=relative_spread, ref_ugm3=ref_ugm3)
    return out.sort_values("bias_max", ascending=False)


def harmonise(x, offset, gain):
    """Invert the fitted sensor = gain * network + offset relation.

    Byrne et al. (2024, Sect. 2.1.1) scale every sensor onto a common
    reference by linear regression before computing the CSI, and describe it
    as a prerequisite. That harmonisation used co-location data, which Leeds
    does not have; the offset and gain fitted over well-mixed hours are the
    field equivalent. Because the map is linear, applying it to daily means
    gives the same answer as applying it to every reading and then averaging.
    """
    return (x - offset) / gain


# --------------------------------------------------------------------------
# Diurnal profiles and site classification
# --------------------------------------------------------------------------
def diurnal_profile(s, tz=LOCAL_TZ, by_daytype=True, stat="median"):
    """Hourly average by local clock time. With by_daytype returns separate
    weekday and weekend columns."""
    local = s.copy()
    local.index = local.index.tz_convert(tz)

    if not by_daytype:
        return local.groupby(local.index.hour).agg(stat)

    weekend = local.index.dayofweek >= 5
    return pd.DataFrame({
        "weekday": local[~weekend].groupby(local.index[~weekend].hour).agg(stat),
        "weekend": local[weekend].groupby(local.index[weekend].hour).agg(stat),
    }).reindex(range(24))


LEEDS_CENTRE = (53.7997, -1.5492)   # City Square


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi   = p2 - p1
    dlmb   = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def classify_sites(coords, centre=LEEDS_CENTRE, edges=(3, 8, 15),
                   labels=("city centre", "inner urban", "suburban", "rural")):
    """Add km_from_centre and site_type columns to a coords DataFrame.
    This is distance-based, not a land-use classification."""
    d = haversine_km(centre[0], centre[1],
                     coords["lat"].to_numpy(), coords["lon"].to_numpy())
    out = coords.copy()
    out["km_from_centre"] = np.round(d, 2)
    out["site_type"] = pd.cut(out["km_from_centre"],
                              bins=[-np.inf, *edges, np.inf],
                              labels=list(labels))
    return out


def nearest_neighbours(coords, target, k=N_NEIGHBOURS):
    """The k closest sensors to `target`, as a Series of distances in km."""
    others = coords.drop(index=target)
    d = haversine_km(coords.loc[target, "lat"], coords.loc[target, "lon"],
                     others["lat"].to_numpy(), others["lon"].to_numpy())
    return pd.Series(d, index=others.index).sort_values().head(k)