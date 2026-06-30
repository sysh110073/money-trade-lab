from __future__ import annotations

import math
from statistics import NormalDist


_NORMAL = NormalDist()


def probabilistic_sharpe_ratio(
    sharpe: float,
    benchmark_sharpe: float = 0.0,
    observations: int = 0,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    if observations <= 1 or not math.isfinite(sharpe):
        return 0.0
    variance = max(1e-12, 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe * sharpe)
    z_score = (sharpe - benchmark_sharpe) * math.sqrt(observations - 1.0) / math.sqrt(variance)
    return _NORMAL.cdf(z_score)


def deflated_sharpe_ratio(
    sharpe: float,
    observations: int,
    trial_count: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    if observations <= 1 or trial_count <= 1:
        return probabilistic_sharpe_ratio(sharpe, 0.0, observations, skew, kurtosis)
    euler_gamma = 0.5772156649015329
    trials = max(2, int(trial_count))
    sr_std = math.sqrt(1.0 / max(1.0, observations - 1.0))
    expected_max_sharpe = sr_std * (
        (1.0 - euler_gamma) * _NORMAL.inv_cdf(1.0 - 1.0 / trials)
        + euler_gamma * _NORMAL.inv_cdf(1.0 - 1.0 / (trials * math.e))
    )
    return probabilistic_sharpe_ratio(sharpe, expected_max_sharpe, observations, skew, kurtosis)
