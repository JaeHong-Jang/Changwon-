"""공간 점수를 사상 조건부 격자 확률로 보정한다."""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit


def platt_fit(pairs: list[tuple[np.ndarray, np.ndarray]]) -> dict:
    """사상별 격자 쌍으로 비규제 Platt 계수를 적합한다."""
    # 유효한 점수와 이진 라벨을 사상 단위로 검증해 합친다.
    if not pairs:
        raise ValueError("보정 사상이 비었다")
    xs, ys = [], []
    for score, label in pairs:
        score, label = np.asarray(score, float), np.asarray(label)
        if score.shape != label.shape or not np.isfinite(score).all() or not np.isin(label, [0, 1]).all():
            raise ValueError("보정 점수·라벨이 유효하지 않다")
        xs.append(logit(np.clip(score, 1e-6, 1 - 1e-6)))
        ys.append(label.astype(float))
    x, y = np.concatenate(xs), np.concatenate(ys)
    if np.unique(y).size != 2:
        return {"c": np.nan, "d": np.nan, "n_cells": len(y), "n_events": len(pairs),
                "converged": False, "failure_reason": "보정 라벨이 단일 클래스다"}

    # 이진 교차엔트로피와 기울기를 같은 격자 가중치로 최소화한다.
    design = np.column_stack((np.ones(len(x)), x))

    # 최적화에 전달할 목적함수와 기울기를 정의한다.
    def objective(beta):
        """Platt 로그우도 손실과 해석적 기울기를 반환한다."""
        # 안정적인 logaddexp로 손실을 계산한다.
        eta = design @ beta
        loss = np.logaddexp(0, eta).sum() - y @ eta
        gradient = design.T @ (expit(eta) - y)
        return loss, gradient

    # 무규제 최적화가 수렴하지 않으면 계수를 사용 불가로 표시한다.
    result = minimize(objective, [float(logit(np.clip(y.mean(), 1e-6, 1 - 1e-6))), 0.0],
                      method="BFGS", jac=True, options={"gtol": 1e-5})
    converged = bool(result.success and np.isfinite(result.x).all())
    params = {"c": float(result.x[0]), "d": float(result.x[1]), "n_cells": len(y),
              "n_events": len(pairs), "converged": converged}
    if not converged:
        params["failure_reason"] = str(result.message) if not result.success else "보정 계수가 비유한이다"
    return params


def platt_predict(params: dict, s: np.ndarray) -> np.ndarray:
    """Platt 계수로 잘린 공간 점수를 조건부 확률로 바꾼다."""
    # 비수렴 계수는 사용하지 않고 전 격자를 결측으로 돌려준다.
    score = np.asarray(s, dtype=float)
    if params.get("converged") is False:
        return np.full(score.shape, np.nan, dtype=float)

    # 0과 1에서 로그오즈가 무한대가 되지 않도록 절단한다.
    return expit(params["c"] + params["d"] * logit(np.clip(score, 1e-6, 1 - 1e-6)))


def _calibration(years, excluded, fit_scores, labels_by_year):
    """각 보정 사상을 학습에서 제외한 점수·라벨 쌍을 만든다."""
    # 연도 키와 격자 라벨의 1:1 관계를 확인한다.
    selected = tuple(sorted(set(years) - set(excluded)))
    if not selected or any(year not in labels_by_year for year in selected):
        raise ValueError("개발 양성 사상과 보정 라벨의 1:1 관계가 깨졌다")

    # 각 사상의 점수에서 평가 사상과 해당 보정 사상을 모두 제외한다.
    pairs = [(fit_scores(tuple(year for year in selected if year != j)), labels_by_year[j]) for j in selected]
    params = platt_fit(pairs)
    params["fit_events"] = list(selected)
    return params


def v1_positive(e, dev_years, fit_scores, labels_by_year):
    """양성 평가 사상을 공간 학습과 보정 양쪽에서 제외한다."""
    # 평가 사상과 보정 사상의 이중 제외 점수를 만든다.
    years = tuple(sorted(set(map(str, dev_years))))
    event = str(e)
    if event not in years:
        raise ValueError("평가 사상이 개발 양성 목록에 없다")
    score = fit_scores(tuple(year for year in years if year != event))
    return score, _calibration(years, {event}, fit_scores, labels_by_year)


def v1_negative(dev_years, fit_scores, labels_by_year):
    """음성 사상에 개발 양성 전체 적합 점수와 LOEO 보정을 쓴다."""
    # 음성 사상은 공간 학습에 없으므로 개발 양성 전체를 사용한다.
    years = tuple(sorted(set(map(str, dev_years))))
    return fit_scores(years), _calibration(years, set(), fit_scores, labels_by_year)


def v3(early_years=("2006", "2012", "2014", "2016", "2019"), fit_scores=None, labels_by_year=None):
    """2019년까지 개발 양성만으로 홀드아웃용 점수와 보정을 고정한다."""
    # 연도 경계를 검증해 2020년 이후 자료 유입을 막는다.
    years = tuple(sorted(set(map(str, early_years))))
    if any(int(year) > 2019 for year in years):
        raise ValueError("V3에는 2020년 이후 사상을 쓸 수 없다")
    return fit_scores(years), _calibration(years, set(), fit_scores, labels_by_year)


def scenario(dev_years, fit_scores, labels_by_year):
    """개발 전체 공간 점수와 LOEO 보정으로 보고용 지도를 만든다."""
    # 보고용 점수는 음성 사상의 개발 전체 보정 규칙을 공유한다.
    return v1_negative(dev_years, fit_scores, labels_by_year)
