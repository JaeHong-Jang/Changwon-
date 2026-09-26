"""고정 Cauchy 사전분포의 사상 로지스틱 MAP를 계산한다."""

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit


def _labels(y):
    """유한한 이진 라벨과 하나 이상의 양성을 요구한다."""
    # 결측이나 이진값 밖의 라벨을 조용히 제거하지 않는다.
    y = np.asarray(y, dtype=float)
    if y.ndim != 1 or not len(y) or not np.isin(y, [0, 1]).all():
        raise ValueError("y must be a nonempty binary vector")
    if not y.sum():
        raise ValueError("no positive events")
    return y


def _optimize(z, y, params, intercept_only=False):
    """해석적 기울기로 고정 사전분포의 음의 로그사후를 최소화한다."""
    # 절편 전용 모형에는 기울기 열과 사전분포를 넣지 않는다.
    design = np.ones((len(y), 1)) if intercept_only else np.column_stack((np.ones(len(y)), z))
    widths = np.array([10.0] if intercept_only else [10.0, 2.5])

    def objective(beta):
        """음의 로그사후와 그 기울기를 동시에 반환한다."""
        # logaddexp로 완전 분리에서도 오버플로를 피한다.
        eta = design @ beta
        value = np.sum(np.logaddexp(0, eta) - y * eta) + np.log1p((beta / widths) ** 2).sum()
        gradient = design.T @ (expit(eta) - y) + 2 * beta / (widths ** 2 + beta ** 2)
        return float(value), gradient

    # 실패 원인을 매개변수에 남기고 예측 함수에서 NA로 전파한다.
    result = minimize(objective, np.zeros(len(widths)), jac=True, method="L-BFGS-B",
                      options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8})
    params.update(a=float(result.x[0]), b=0.0 if intercept_only else float(result.x[1]),
                  converged=bool(result.success and np.isfinite(result.x).all()))
    if not params["converged"]:
        params["reason"] = "optimizer_failure: " + str(result.message)
    return params


def fit(raw, y, *, transform="log1p"):
    """학습값만으로 척도화한 단일 특징 로지스틱 MAP를 적합한다."""
    # 사전 고정 변환과 자료 길이를 검사한다.
    y = _labels(y)
    raw = np.asarray(raw, dtype=float)
    if transform != "log1p":
        raise ValueError("protocol v1.1 requires log1p")
    if raw.shape != y.shape or not np.isfinite(raw).all() or (raw < 0).any():
        raise ValueError("raw must be finite nonnegative values matching y")
    x = np.log1p(raw)
    params = dict(a=np.nan, b=np.nan, center=float(x.mean()), scale=float(2 * x.std(ddof=0)),
                  transform=transform, n=len(y), n_pos=int(y.sum()), converged=False)
    if np.ptp(x) == 0 or params["scale"] == 0:
        params["scale"] = 0.0
        params["reason"] = "zero_scale"
        return params
    return _optimize((x - params["center"]) / params["scale"], y, params)


def fit_intercept_only(y):
    """같은 절편 Cauchy 사전분포를 쓰는 절편 전용 MAP를 적합한다."""
    # 절편 전용 모형은 특징의 척도나 결측에 의존하지 않는다.
    y = _labels(y)
    params = dict(a=np.nan, b=0.0, center=0.0, scale=1.0, transform="intercept_only",
                  n=len(y), n_pos=int(y.sum()), converged=False)
    return _optimize(None, y, params, intercept_only=True)


def predict_raw(params: dict, raw: np.ndarray) -> np.ndarray:
    """저장된 학습 척도로 원자료를 변환해 MAP 확률을 반환한다."""
    # 실패한 적합은 절편 전용 여부와 무관하게 NA로 반환한다.
    raw = np.asarray(raw, dtype=float)
    if not params.get("converged", False):
        return np.full(raw.shape, np.nan)
    if params.get("transform") == "intercept_only":
        return np.full(raw.shape, expit(params["a"]))
    if params.get("scale", 0) <= 0:
        return np.full(raw.shape, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        p = expit(params["a"] + params["b"] * (np.log1p(raw) - params["center"]) / params["scale"])
    return np.where(np.isfinite(raw) & (raw >= 0), p, np.nan)
