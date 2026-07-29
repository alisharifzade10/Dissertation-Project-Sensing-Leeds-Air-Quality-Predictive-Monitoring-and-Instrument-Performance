"""
Baseline separation for the Leeds PurpleAir network.

Motivation
----------
A PM2.5 reading at any site mixes three things: air blown in from outside the
city (regional background), the general urban haze, and whatever is happening
within a few hundred metres of the sensor (a road, a wood burner, a bonfire).
Comparing raw time series between sites therefore compares mostly the regional
signal, which every sensor shares, and hides the local differences that make a
dense network worth deploying at all.

This module splits each series into

    C_i(t) = B(t) + I_i(t)

where B(t) is a baseline common to the network at time t and I_i(t) is the
local increment at sensor i. The decomposition follows the standard practice
of separating regional, urban and local contributions to urban particulate
matter (Lenschow et al., 2001, Atmos. Environ. 35, S23-S33).

Two families of baseline are provided:

* SPATIAL (`network_baseline`) — a low quantile across sensors at each
  timestamp. Rationale: at any moment the cleanest sites in the network are
  the ones with no local source active, so their concentration approximates
  the air everyone is breathing before local additions. Requires a reasonably
  dense network at that timestamp.

* TEMPORAL (`rolling_baseline`) — a low quantile of a centred time window at a
  single site. Rationale: local sources are intermittent, so the lower envelope
  of a site's own record tracks the background it sits in. Works for a single
  sensor with no network required, but cannot separate a persistent local
  source from the background.

A note on night-time baselines
------------------------------
Taking a quiet night as "background" is intuitive — traffic is minimal between
about 01:00 and 05:00 — but it is not automatically clean air. The nocturnal
boundary layer is shallow, so whatever *is* emitted accumulates in a thinner
volume, and in winter domestic solid-fuel burning peaks in the evening and
decays overnight. Night is therefore used here as a *conditioning* period for
isolating instrument behaviour (`instrument_offset`), not as the definition of
background concentration: during quiet, well-mixed night hours the sensors
should all be looking at the same air, so any systematic difference between a
sensor and its network is a property of the instrument rather than of the air.

All functions take and return pandas objects with a tz-aware UTC
DatetimeIndex, matching `network_hourly_sensors.parquet`.
"""
import numpy as np
import pandas as pd


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------
def network_baseline(hm, q=0.10, min_sensors=5):
    """Spatial baseline: the q-th quantile across sensors at each timestamp.

    Parameters
    ----------
    hm : DataFrame (timestamps x sensors) of concentrations.
    q : float, quantile across sensors. 0.10 keeps the estimate near the
        cleaner end of the network without chasing a single low outlier
        (which q=0 would do, and which a faulty low-reading sensor would win).
    min_sensors : int, timestamps with fewer reporting sensors give NaN —
        a quantile over three sensors is not a network estimate.

    Returns
    -------
    Series of baseline values, NaN where the network was too thin.
    """
    n = hm.notna().sum(axis=1)
    base = hm.quantile(q, axis=1)
    return base.where(n >= min_sensors)


def rolling_baseline(s, window="7D", q=0.05, min_frac=0.25):
    """Temporal baseline: a low quantile of a centred rolling window.

    Parameters
    ----------
    s : Series with a DatetimeIndex.
    window : pandas offset string. 7 days is long enough to span a synoptic
        weather episode and short enough to follow seasonal change.
    q : float, quantile within the window.
    min_frac : float, the window must be at least this full (as a fraction of
        the hours it could hold) or the result is NaN. Stops a baseline being
        drawn from two surviving readings in a gap.

    Returns
    -------
    Series aligned to `s`.
    """
    if not isinstance(s.index, pd.DatetimeIndex):
        raise TypeError("rolling_baseline needs a DatetimeIndex")

    hours = pd.Timedelta(window) / pd.Timedelta("1h")
    roll = s.rolling(window, center=True, min_periods=1)
    base = roll.quantile(q)
    count = roll.count()
    return base.where(count >= max(2, min_frac * hours))


def local_increment(hm, baseline):
    """Concentration above baseline, per sensor. Negative values are kept:
    they are informative (a sensor reading below the regional baseline may be
    reading low), and clipping them would bias every mean upwards."""
    return hm.sub(baseline, axis=0)


# --------------------------------------------------------------------------
# Night-time conditioning and instrument diagnostics
# --------------------------------------------------------------------------
def night_mask(index, tz="Europe/London", hours=(1, 5)):
    """Boolean mask for local-clock night hours, inclusive of both ends.

    Hours are interpreted in local time because "night" is a clock concept
    tied to human activity, and British Summer Time shifts it by an hour
    relative to UTC for half the year.
    """
    local = index.tz_convert(tz)
    lo, hi = hours
    return (local.hour >= lo) & (local.hour <= hi)


def well_mixed_mask(hm, baseline, max_spread=None, spread_q=0.5):
    """Timestamps when the network is spatially uniform.

    Spread is the inter-quartile range across sensors. A small spread means
    every sensor sees much the same air, which is the condition under which a
    persistent per-sensor difference can be attributed to the instrument
    rather than to a genuine local source.

    If `max_spread` is None it is set to the `spread_q` quantile of the
    observed spread, i.e. the calmest half of timestamps by default.
    """
    spread = hm.quantile(0.75, axis=1) - hm.quantile(0.25, axis=1)
    if max_spread is None:
        max_spread = spread.quantile(spread_q)
    return (spread <= max_spread) & baseline.notna(), float(max_spread)


def instrument_offset(hm, tz="Europe/London", night_hours=(1, 5),
                      q=0.10, min_sensors=5, spread_q=0.5, min_hours=100):
    """Per-sensor bias relative to the network during quiet, well-mixed nights.

    The logic: restrict to night hours (little local emission), then to
    timestamps when the network is spatially uniform (well mixed). Under those
    conditions every working sensor should report close to the same value, so
    a sensor's median departure from the network is an estimate of its own
    bias rather than of its surroundings.

    Two forms of bias are reported because they have different causes:
      * additive offset  (ug/m3)  — median of (sensor - network median).
        Typical of a contaminated optical path or a drifting zero.
      * multiplicative gain (ratio) — median of (sensor / network median),
        computed only where the network median exceeds 1 ug/m3 so the ratio
        is meaningful. Typical of a calibration-slope error.

    Returns a DataFrame indexed by sensor with columns:
        offset_ugm3, gain_ratio, n_hours, median_network_ugm3
    """
    base = network_baseline(hm, q=q, min_sensors=min_sensors)
    mixed, used_spread = well_mixed_mask(hm, base, spread_q=spread_q)
    night = pd.Series(night_mask(hm.index, tz=tz, hours=night_hours),
                      index=hm.index)
    sel = night & mixed

    sub = hm.loc[sel]
    net = hm.loc[sel].median(axis=1)

    diff = sub.sub(net, axis=0)
    denom = net.where(net > 1.0)
    ratio = sub.div(denom, axis=0)

    out = pd.DataFrame({
        "offset_ugm3": diff.median(),
        "gain_ratio": ratio.median(),
        "n_hours": sub.notna().sum(),
        "median_network_ugm3": float(net.median()),
    })
    out.attrs["max_spread_used"] = used_spread
    out.attrs["n_timestamps"] = int(sel.sum())
    return out.loc[out["n_hours"] >= min_hours].sort_values("offset_ugm3")


# --------------------------------------------------------------------------
# Diurnal profiles
# --------------------------------------------------------------------------
def diurnal_profile(s, tz="Europe/London", by_daytype=True, stat="median"):
    """Average value by local hour of day.

    With `by_daytype`, returns a DataFrame with 'weekday' and 'weekend'
    columns. The weekday/weekend contrast is the standard way to separate a
    traffic-driven signal (strong weekday morning peak) from sources that do
    not follow the working week (domestic heating, regional transport).
    """
    local = s.copy()
    local.index = local.index.tz_convert(tz)
    hour = local.index.hour

    if not by_daytype:
        return local.groupby(hour).agg(stat)

    weekend = local.index.dayofweek >= 5
    out = pd.DataFrame({
        "weekday": local[~weekend].groupby(local.index[~weekend].hour).agg(stat),
        "weekend": local[weekend].groupby(local.index[weekend].hour).agg(stat),
    })
    return out.reindex(range(24))


# --------------------------------------------------------------------------
# Site classification
# --------------------------------------------------------------------------
LEEDS_CENTRE = (53.7997, -1.5492)   # City Square


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def classify_sites(coords, centre=LEEDS_CENTRE,
                   edges=(3, 8, 15),
                   labels=("city centre", "inner urban", "suburban", "rural")):
    """Crude urban-rural classification by distance from the city centre.

    This is a geometric proxy, not a land-use survey: a sensor 10 km out on a
    main road is not really suburban in character. It is used only to group
    sites for comparison, and the group boundaries are reported so the
    grouping can be varied.

    Returns a DataFrame with km_from_centre and site_type.
    """
    d = haversine_km(centre[0], centre[1],
                     coords["lat"].to_numpy(), coords["lon"].to_numpy())
    out = coords.copy()
    out["km_from_centre"] = np.round(d, 2)
    out["site_type"] = pd.cut(out["km_from_centre"],
                              bins=[-np.inf, *edges, np.inf],
                              labels=list(labels))
    return out


def offset_gain(hm, tz="Europe/London", night_hours=None, n_bins=10,
                q=0.10, min_sensors=5, spread_q=0.5, min_hours=100):
    """Separate additive offset from multiplicative gain by regression.

    `instrument_offset` reports both a median difference and a median ratio,
    but at low concentrations the two are entangled: a sensor reading a
    constant 5 ug/m3 too high also shows a large ratio when the air is clean.
    Regressing a sensor's value on the network median across the concentration
    range separates them properly:

        sensor = gain * network + offset

    an intercept away from 0 is an additive bias, a slope away from 1 is a
    calibration-slope error, and a sensor can have both.

    The fit is made robust without extra dependencies by binning the network
    median into `n_bins` quantile bins, taking the median sensor value in each
    bin, and least-squares fitting a line to those bin medians. Individual
    outlying hours therefore cannot drag the fit.

    By default all well-mixed hours are used, not just night: spatial
    uniformity already implies no local source is active, and using the full
    day spans a wider concentration range, which the slope estimate needs.
    Pass `night_hours=(1, 5)` to restrict to quiet nights as well.

    Returns a DataFrame indexed by sensor with offset_ugm3, gain, n_hours,
    n_bins_used and r2 (fit quality on the bin medians).
    """
    base = network_baseline(hm, q=q, min_sensors=min_sensors)
    mixed, used_spread = well_mixed_mask(hm, base, spread_q=spread_q)
    sel = mixed
    if night_hours is not None:
        sel = sel & pd.Series(night_mask(hm.index, tz=tz, hours=night_hours),
                              index=hm.index)

    sub = hm.loc[sel]
    net = sub.median(axis=1)
    ok = net.notna()
    sub, net = sub.loc[ok], net.loc[ok]
    if len(net) < 2:
        return pd.DataFrame(columns=["offset_ugm3", "gain", "n_hours",
                                     "n_bins_used", "r2"])

    bins = pd.qcut(net, n_bins, duplicates="drop")

    rows = {}
    for name in sub.columns:
        s = sub[name]
        pair = pd.DataFrame({"net": net, "sen": s, "bin": bins}).dropna()
        if len(pair) < min_hours:
            continue
        g = pair.groupby("bin", observed=True).median(numeric_only=True)
        g = g.dropna()
        if len(g) < 3:
            continue
        x, y = g["net"].to_numpy(), g["sen"].to_numpy()
        gain, offset = np.polyfit(x, y, 1)
        pred = gain * x + offset
        ss_res = float(((y - pred) ** 2).sum())
        ss_tot = float(((y - y.mean()) ** 2).sum())
        rows[name] = {
            "offset_ugm3": offset,
            "gain": gain,
            "n_hours": int(len(pair)),
            "n_bins_used": int(len(g)),
            "r2": 1 - ss_res / ss_tot if ss_tot > 0 else np.nan,
        }

    out = pd.DataFrame(rows).T
    out.attrs["max_spread_used"] = used_spread
    out.attrs["n_timestamps"] = int(sel.sum())
    return out.sort_values("offset_ugm3", ascending=False)
