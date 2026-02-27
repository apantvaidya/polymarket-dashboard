from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


@dataclass
class FitResult:
    lambda_home: float
    lambda_away: float
    error: float


def implied_prob(odds: float) -> float:
    if odds <= 1.0:
        raise ValueError("Decimal odds must be > 1.0")
    return 1.0 / odds


def no_vig_two_way(prob_a: float, prob_b: float) -> Tuple[float, float]:
    denom = prob_a + prob_b
    if denom <= 0:
        raise ValueError("Invalid probabilities for no-vig normalization")
    return prob_a / denom, prob_b / denom


def _poisson_pmf(lam: float, k: int) -> float:
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def _poisson_pmf_list(lam: float, max_k: int) -> List[float]:
    pmf = [0.0] * (max_k + 1)
    pmf[0] = math.exp(-lam)
    for k in range(1, max_k + 1):
        pmf[k] = pmf[k - 1] * lam / k
    return pmf


def _max_goals(lam_total: float) -> int:
    return max(10, int(math.ceil(lam_total + 10.0 * math.sqrt(lam_total + 1.0))))


def _total_cdf_from_lam(lam_total: float, max_k: int) -> List[float]:
    pmf = _poisson_pmf_list(lam_total, max_k)
    cdf = [0.0] * (max_k + 1)
    running = 0.0
    for k in range(max_k + 1):
        running += pmf[k]
        cdf[k] = running
    return cdf


def _prob_total_ge(lam_total: float, threshold: int) -> float:
    max_k = _max_goals(lam_total)
    cdf = _total_cdf_from_lam(lam_total, max_k)
    if threshold <= 0:
        return 1.0
    if threshold > max_k:
        return 0.0
    return 1.0 - cdf[threshold - 1]


def _prob_total_le(lam_total: float, threshold: int) -> float:
    max_k = _max_goals(lam_total)
    cdf = _total_cdf_from_lam(lam_total, max_k)
    if threshold < 0:
        return 0.0
    if threshold >= max_k:
        return 1.0
    return cdf[threshold]


def total_over_under_probs(lam_total: float, line: float) -> Tuple[float, float]:
    n = int(math.floor(line))
    frac = round(line - n, 2)

    if frac == 0.0:
        over = _prob_total_ge(lam_total, n + 1)
        under = _prob_total_le(lam_total, n - 1)
        return over, under
    if frac == 0.5:
        over = _prob_total_ge(lam_total, n + 1)
        under = 1.0 - over
        return over, under
    if frac == 0.25:
        over = _prob_total_ge(lam_total, n + 1)
        under = 0.5 * _prob_total_le(lam_total, n - 1) + 0.5 * _prob_total_le(lam_total, n)
        return over, under
    if frac == 0.75:
        over = 0.5 * _prob_total_ge(lam_total, n + 1) + 0.5 * _prob_total_ge(lam_total, n + 2)
        under = _prob_total_le(lam_total, n)
        return over, under

    raise ValueError(f"Unsupported line fraction: {line}")


def _prob_diff_ge(lam_home: float, lam_away: float, threshold: int) -> float:
    lam_total = lam_home + lam_away
    max_k = _max_goals(lam_total)
    pmf_home = _poisson_pmf_list(lam_home, max_k)
    pmf_away = _poisson_pmf_list(lam_away, max_k)
    prob = 0.0
    for h in range(max_k + 1):
        if pmf_home[h] == 0:
            continue
        for a in range(max_k + 1):
            if h - a >= threshold:
                prob += pmf_home[h] * pmf_away[a]
    return prob


def _prob_home_draw_away(lam_home: float, lam_away: float) -> Tuple[float, float, float]:
    lam_total = lam_home + lam_away
    max_k = _max_goals(lam_total)
    pmf_home = _poisson_pmf_list(lam_home, max_k)
    pmf_away = _poisson_pmf_list(lam_away, max_k)

    p_draw = 0.0
    p_home_win = 0.0
    p_away_win = 0.0
    for h in range(max_k + 1):
        for a in range(max_k + 1):
            p = pmf_home[h] * pmf_away[a]
            if h > a:
                p_home_win += p
            elif h < a:
                p_away_win += p
            else:
                p_draw += p
    return p_home_win, p_draw, p_away_win


def fair_moneyline_probs(lam_home: float, lam_away: float) -> Dict[str, float]:
    home, draw, away = _prob_home_draw_away(lam_home, lam_away)
    return {"home": home, "draw": draw, "away": away}


def fair_btts_prob(lam_home: float, lam_away: float) -> float:
    # P(H>=1 and A>=1) = 1 - P(H=0) - P(A=0) + P(H=0,A=0)
    p_h0 = math.exp(-lam_home)
    p_a0 = math.exp(-lam_away)
    return 1.0 - p_h0 - p_a0 + (p_h0 * p_a0)


def fair_spread_prob(lam_home: float, lam_away: float, line: float) -> float:
    # Home handicap line (half-goal). Win if H + line > A -> D > -line
    threshold = math.floor(-line) + 1
    return _prob_diff_ge(lam_home, lam_away, int(threshold))


def asian_total_over_prob(lam_total: float, line: float) -> float:
    n = int(math.floor(line))
    frac = round(line - n, 2)
    if frac == 0.75:
        return 0.5 * _prob_total_ge(lam_total, n + 1) + 0.5 * _prob_total_ge(lam_total, n + 2)
    if frac == 0.25:
        return _prob_total_ge(lam_total, n + 1)
    return total_over_under_probs(lam_total, line)[0]


def asian_handicap_home_prob(lam_home: float, lam_away: float, line: float) -> float:
    if line == -0.75:
        return 0.5 * _prob_diff_ge(lam_home, lam_away, 1) + 0.5 * _prob_diff_ge(lam_home, lam_away, 2)
    raise ValueError("Currently only -0.75 is supported in the fitter")


def fit_lambdas_from_asian_markets(
    over_odds: float,
    under_odds: float,
    home_odds: float,
    away_odds: float,
    total_line: float = 2.75,
    handicap_line: float = -0.75,
    total_min: float = 0.5,
    total_max: float = 5.5,
    total_step: float = 0.02,
    split_step: float = 0.02,
    refine_step: float = 0.005,
    refine_radius: float = 0.12,
) -> FitResult:
    p_over_raw = implied_prob(over_odds)
    p_under_raw = implied_prob(under_odds)
    p_over, _ = no_vig_two_way(p_over_raw, p_under_raw)

    p_home_raw = implied_prob(home_odds)
    p_away_raw = implied_prob(away_odds)
    p_home, _ = no_vig_two_way(p_home_raw, p_away_raw)

    best = FitResult(lambda_home=1.0, lambda_away=1.0, error=float("inf"))

    total = total_min
    while total <= total_max + 1e-9:
        home = 0.05
        while home <= total - 0.05 + 1e-9:
            away = total - home
            model_over = asian_total_over_prob(total, total_line)
            model_home = asian_handicap_home_prob(home, away, handicap_line)
            err = (model_over - p_over) ** 2 + (model_home - p_home) ** 2
            if err < best.error:
                best = FitResult(lambda_home=home, lambda_away=away, error=err)
            home += split_step
        total += total_step

    # Local refinement around the best point
    t_min = max(total_min, best.lambda_home + best.lambda_away - refine_radius)
    t_max = min(total_max, best.lambda_home + best.lambda_away + refine_radius)
    total = t_min
    while total <= t_max + 1e-9:
        home_min = max(0.05, best.lambda_home - refine_radius)
        home_max = min(total - 0.05, best.lambda_home + refine_radius)
        home = home_min
        while home <= home_max + 1e-9:
            away = total - home
            model_over = asian_total_over_prob(total, total_line)
            model_home = asian_handicap_home_prob(home, away, handicap_line)
            err = (model_over - p_over) ** 2 + (model_home - p_home) ** 2
            if err < best.error:
                best = FitResult(lambda_home=home, lambda_away=away, error=err)
            home += refine_step
        total += refine_step

    return best


def fit_lambdas_from_asian_probs(
    over_prob_raw: float,
    under_prob_raw: float,
    home_prob_raw: float,
    away_prob_raw: float,
    total_line: float = 2.75,
    handicap_line: float = -0.75,
    total_min: float = 0.5,
    total_max: float = 5.5,
    total_step: float = 0.02,
    split_step: float = 0.02,
    refine_step: float = 0.005,
    refine_radius: float = 0.12,
) -> FitResult:
    p_over, _ = no_vig_two_way(over_prob_raw, under_prob_raw)
    p_home, _ = no_vig_two_way(home_prob_raw, away_prob_raw)

    best = FitResult(lambda_home=1.0, lambda_away=1.0, error=float("inf"))

    total = total_min
    while total <= total_max + 1e-9:
        home = 0.05
        while home <= total - 0.05 + 1e-9:
            away = total - home
            model_over = asian_total_over_prob(total, total_line)
            model_home = asian_handicap_home_prob(home, away, handicap_line)
            err = (model_over - p_over) ** 2 + (model_home - p_home) ** 2
            if err < best.error:
                best = FitResult(lambda_home=home, lambda_away=away, error=err)
            home += split_step
        total += total_step

    # Local refinement around the best point
    t_min = max(total_min, best.lambda_home + best.lambda_away - refine_radius)
    t_max = min(total_max, best.lambda_home + best.lambda_away + refine_radius)
    total = t_min
    while total <= t_max + 1e-9:
        home_min = max(0.05, best.lambda_home - refine_radius)
        home_max = min(total - 0.05, best.lambda_home + refine_radius)
        home = home_min
        while home <= home_max + 1e-9:
            away = total - home
            model_over = asian_total_over_prob(total, total_line)
            model_home = asian_handicap_home_prob(home, away, handicap_line)
            err = (model_over - p_over) ** 2 + (model_home - p_home) ** 2
            if err < best.error:
                best = FitResult(lambda_home=home, lambda_away=away, error=err)
            home += refine_step
        total += refine_step

    return best


def fair_total_map(lam_home: float, lam_away: float, lines: Iterable[float]) -> Dict[float, Dict[str, float]]:
    lam_total = lam_home + lam_away
    out: Dict[float, Dict[str, float]] = {}
    for line in lines:
        over, under = total_over_under_probs(lam_total, line)
        out[line] = {"over": over, "under": under}
    return out


def fair_spread_map(lam_home: float, lam_away: float, lines: Iterable[float]) -> Dict[float, Dict[str, float]]:
    out: Dict[float, Dict[str, float]] = {}
    for line in lines:
        home = fair_spread_prob(lam_home, lam_away, line)
        away = 1.0 - home
        out[line] = {"home": home, "away": away}
    return out


def fair_price_map(
    over_odds: float,
    under_odds: float,
    home_odds: float,
    away_odds: float,
    total_line: float = 2.75,
    handicap_line: float = -0.75,
    derived_lines: Iterable[float] = (1.5, 2.5, 3.5, 4.5),
) -> Dict[str, Dict]:
    fit = fit_lambdas_from_asian_markets(
        over_odds=over_odds,
        under_odds=under_odds,
        home_odds=home_odds,
        away_odds=away_odds,
        total_line=total_line,
        handicap_line=handicap_line,
    )
    totals = fair_total_map(fit.lambda_home, fit.lambda_away, derived_lines)
    return {
        "lambda_home": fit.lambda_home,
        "lambda_away": fit.lambda_away,
        "error": fit.error,
        "totals": totals,
    }


def fair_price_map_from_probs(
    over_prob_raw: float,
    under_prob_raw: float,
    home_prob_raw: float,
    away_prob_raw: float,
    total_line: float = 2.75,
    handicap_line: float = -0.75,
    derived_lines: Iterable[float] = (1.5, 2.5, 3.5, 4.5),
) -> Dict[str, Dict]:
    fit = fit_lambdas_from_asian_probs(
        over_prob_raw=over_prob_raw,
        under_prob_raw=under_prob_raw,
        home_prob_raw=home_prob_raw,
        away_prob_raw=away_prob_raw,
        total_line=total_line,
        handicap_line=handicap_line,
    )
    totals = fair_total_map(fit.lambda_home, fit.lambda_away, derived_lines)
    return {
        "lambda_home": fit.lambda_home,
        "lambda_away": fit.lambda_away,
        "error": fit.error,
        "totals": totals,
    }


def fair_markets_from_probs(
    over_prob_raw: float,
    under_prob_raw: float,
    home_prob_raw: float,
    away_prob_raw: float,
    total_line: float = 2.75,
    handicap_line: float = -0.75,
    derived_totals: Iterable[float] = (1.5, 2.5, 3.5, 4.5),
    derived_spreads: Iterable[float] = (-1.5, -0.5, 0.5, 1.5),
) -> Dict[str, Dict]:
    fit = fit_lambdas_from_asian_probs(
        over_prob_raw=over_prob_raw,
        under_prob_raw=under_prob_raw,
        home_prob_raw=home_prob_raw,
        away_prob_raw=away_prob_raw,
        total_line=total_line,
        handicap_line=handicap_line,
    )
    moneyline = fair_moneyline_probs(fit.lambda_home, fit.lambda_away)
    totals = fair_total_map(fit.lambda_home, fit.lambda_away, derived_totals)
    spreads = fair_spread_map(fit.lambda_home, fit.lambda_away, derived_spreads)
    btts_yes = fair_btts_prob(fit.lambda_home, fit.lambda_away)
    return {
        "lambda_home": fit.lambda_home,
        "lambda_away": fit.lambda_away,
        "error": fit.error,
        "moneyline": moneyline,
        "totals": totals,
        "spreads": spreads,
        "btts": {"yes": btts_yes, "no": 1.0 - btts_yes},
    }
