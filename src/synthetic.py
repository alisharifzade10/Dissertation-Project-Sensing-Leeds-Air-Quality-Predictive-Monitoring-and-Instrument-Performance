"""
Synthetic fault injection, used to calibrate what a CSI value means.

The CSI is a fraction of agreeing days, so it has no units and a value of 0.3
carries no information on its own about how badly a sensor is behaving. Byrne
et al. (2024, Table 3) solved this by perturbing a real sensor series in known
ways and recomputing the index. Their numbers come from Irish winter
concentrations; the CSI switches between a strict and a lenient regime at
15 ug/m3, so its response depends on the level the network actually sits at,
and Leeds air is several times cleaner. The same exercise therefore has to be
repeated on a Leeds series before their scale can be used here.

Faults are injected into a real daily series rather than into a simulated one,
so the day-to-day structure, the gaps and the concentration distribution are
those of the network under study.
"""
import numpy as np
import pandas as pd

from src.csi import csi_pair, mean_csi_against


def apply_fault(series, kind, size, seed=0):
    """Return a copy of `series` with one fault of the given size applied.

    kind        size means
    offset      constant added, ug/m3
    gain        multiplicative factor (1.0 = unchanged)
    variance    factor multiplying the departure from the sensor's own mean,
                which changes the spread while leaving the mean alone
    noise       standard deviation of added Gaussian noise, ug/m3
    freeze      fraction of the record, at the end, held at the last value

    Values are clipped at zero afterwards because a negative concentration is
    not something the instrument can report.
    """
    s = series.copy()
    rng = np.random.default_rng(seed)

    if kind == "offset":
        s = s + size
    elif kind == "gain":
        s = s * size
    elif kind == "variance":
        s = s.mean() + size * (s - s.mean())
    elif kind == "noise":
        s = s + rng.normal(0, size, len(s))
    elif kind == "freeze":
        n_frozen = int(round(size * len(s)))
        if n_frozen > 0:
            s.iloc[-n_frozen:] = s.iloc[-n_frozen - 1] if n_frozen < len(s) else s.iloc[0]
    else:
        raise ValueError(f"unknown fault kind: {kind}")

    return s.clip(lower=0)


def csi_response(series, others, kind, sizes, seed=0):
    """CSI of a faulted series against itself and against the network.

    `series` is one sensor's daily means; `others` is a days x sensors frame of
    the rest of the network. The self comparison reproduces Byrne et al.'s
    Table 3 design and isolates the effect of the fault. The network comparison
    is the quantity the pipeline actually reports in notebook 05, and is the
    one to read a real sensor's score against.
    """
    rows = []
    for size in sizes:
        faulted = apply_fault(series, kind, size, seed=seed)
        self_csi, n_self = csi_pair(series.to_numpy(), faulted.to_numpy())

        net_csi, n_pairs = mean_csi_against(faulted, others)

        rows.append({
            "fault": kind,
            "size": size,
            "csi_self": round(self_csi, 3),
            "csi_network": round(net_csi, 3),
            "n_days": n_self,
            "n_pairs": n_pairs,
        })
    return pd.DataFrame(rows)
