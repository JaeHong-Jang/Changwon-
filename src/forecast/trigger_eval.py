"""사전 고정 사상 검증 분할·예측·지표·주 판정을 계산한다."""

import numpy as np
import pandas as pd

from src.forecast import event_metrics as em
from src.forecast import logit_prior
from src.forecast.time_utils import parse_time


PREDICTION_COLUMNS = ["storm_id", "role", "label", "model", "scheme", "set", "subset", "p", "warn", "p_ref"]
GROUP_COLUMNS = ["model", "scheme", "set", "subset"]
MODEL_FEATURES = {"M_fc24": "r12max_fc24", "M_fc6": "r12max_fc6", "M_obs": "r12max_obs",
                  "M_int": None, "B_clim": None, "B_rule110": "r12max_fc24",
                  "B_rule180": "r12max_fc24", "B_warn": "warn_advisory", "B_warn3": "warn_warning"}
COMMON_FEATURES = ["r12max_fc24", "r12max_fc6", "r12max_obs"]


def prepare_table(storms, features=None, warnings=None, *, include_holdout=False):
    """입력 단계에서 홀드아웃을 걸러 사상당 하나의 특징 행을 만든다."""
    # 홀드아웃 제거를 시각·라벨 변환과 특징 병합보다 먼저 한다.
    data = storms.copy() if include_holdout else storms.loc[storms.role.ne("holdout")].copy()
    if data.storm_id.duplicated().any():
        raise ValueError("storm_id must be unique")
    if features is not None:
        selected = features[features.storm_id.isin(data.storm_id)]
        wide = selected.pivot(index="storm_id", columns="lead_h", values="r12max_fc")
        wide = wide.rename(columns={24: "r12max_fc24", 6: "r12max_fc6"})
        data = data.merge(wide, on="storm_id", how="left", validate="one_to_one")
    if warnings is not None:
        data = data.merge(warnings[warnings.storm_id.isin(data.storm_id)], on="storm_id", how="left", validate="one_to_one")
    for column in [*COMMON_FEATURES, "warn_advisory", "warn_warning", "label"]:
        data[column] = pd.to_numeric(data[column], errors="coerce") if column in data else np.nan
    data["t0"] = pd.to_datetime(data.t0.map(parse_time))
    data["active_year"] = data.active_year.astype(str).str.lower().isin(["true", "1", "1.0"])
    return data.reset_index(drop=True)


def _eligible(data, model, set_name):
    """공통 집합 또는 모형별 전체 집합의 유효 특징 행을 고른다."""
    # 음수 강수량과 무한값은 유효 예보로 취급하지 않는다.
    columns = COMMON_FEATURES if set_name == "common" else []
    columns = list(dict.fromkeys([*columns, *([MODEL_FEATURES[model]] if MODEL_FEATURES[model] else [])]))
    mask = np.ones(len(data), dtype=bool)
    for column in columns:
        mask &= np.isfinite(data[column]) & data[column].ge(0)
    return data.loc[mask]


def _folds(data, scheme):
    """평가 사상과 절대 겹치지 않는 개발 학습집합을 순회한다."""
    # 모든 scheme에서 학습 역할은 development로 한정한다.
    development = data[data.role.eq("development")]
    if scheme == "V1_loso":
        for index in development.index:
            yield str(development.loc[index, "storm_id"]), development.drop(index), development.loc[[index]]
    elif scheme == "V2_retro_year":
        for year in sorted(development.t0.dt.year.unique()):
            yield str(year), development[development.t0.lt(pd.Timestamp(year=int(year), month=1, day=1))], development[development.t0.dt.year.eq(year)]
    else:
        training = development[development.t0.lt(pd.Timestamp("2020-01-01"))] if scheme == "V3_frozen" else development
        yield "frozen", training, data[data.role.eq("holdout")]


def _fit(training, model, fit_fn, intercept_fit_fn):
    """양성이 없는 학습집합을 명시적 실패 매개변수로 변환한다."""
    # 양성 부재와 수렴 실패를 기준 모형으로 대체하지 않는다.
    y = training.label.to_numpy(dtype=float)
    if not len(y) or not y.sum():
        return dict(a=np.nan, b=np.nan, center=np.nan, scale=np.nan, transform="log1p",
                    n=len(y), n_pos=int(y.sum()), converged=False, reason="no_positive_events")
    return intercept_fit_fn(y) if model == "M_int" else fit_fn(training[MODEL_FEATURES[model]].to_numpy(dtype=float), y)


def evaluate(storms, features=None, warnings=None, *, include_holdout=False, fit_fn=None,
             intercept_fit_fn=None, predict_fn=None):
    """각 집합·부분집합 안에서 검증하고 고정 열의 사상 예측표를 만든다."""
    # 주입 함수는 합성 자료에서 학습 사상 누수 여부를 검사하는 데 쓴다.
    fit_fn = logit_prior.fit if fit_fn is None else fit_fn
    intercept_fit_fn = logit_prior.fit_intercept_only if intercept_fit_fn is None else intercept_fit_fn
    predict_fn = logit_prior.predict_raw if predict_fn is None else predict_fn
    data = prepare_table(storms, features, warnings, include_holdout=include_holdout)
    data = data[data.label.isin([0, 1]) & data.role.isin(["development", "holdout"])]
    schemes = ["V1_loso", "V2_retro_year"] + (["V3_frozen", "V3b_frozen_all"] if include_holdout else [])
    records, failures = [], []
    for subset in ("S1", "S2"):
        population = data if subset == "S1" else data[data.label.eq(1) | data.active_year]
        for set_name in ("common", "full"):
            for model, feature in MODEL_FEATURES.items():
                available = _eligible(population, model, set_name)
                for scheme in schemes:
                    for fold, training, testing in _folds(available, scheme):
                        if testing.empty or (scheme == "V2_retro_year" and training.label.sum() < 2):
                            continue
                        # 기준 확률도 해당 모형과 같은 유효 사상·부분집합·fold 학습집합으로 계산한다.
                        rate = float(training.label.mean()) if len(training) else np.nan
                        if model.startswith("M_"):
                            params = _fit(training, model, fit_fn, intercept_fit_fn)
                            raw = np.zeros(len(testing)) if feature is None else testing[feature].to_numpy(dtype=float)
                            probabilities = predict_fn(params, raw)
                            if not params.get("converged", False):
                                failures.append(dict(model=model, scheme=scheme, set=set_name, subset=subset,
                                                     fold=fold, reason=params.get("reason", "optimizer_failure")))
                            alerts = np.where(np.isfinite(probabilities) & np.isfinite(rate), probabilities >= rate, np.nan)
                        elif model == "B_clim":
                            probabilities = np.full(len(testing), rate)
                            alerts = np.where(np.isfinite(probabilities), probabilities >= rate, np.nan)
                        else:
                            threshold = 110 if model == "B_rule110" else 180 if model == "B_rule180" else 1
                            probabilities = testing[feature].ge(threshold).to_numpy(dtype=float)
                            alerts = probabilities
                        for storm, p, warn in zip(testing.itertuples(), probabilities, alerts):
                            records.append(dict(storm_id=storm.storm_id, role=storm.role, label=int(storm.label), model=model,
                                                scheme=scheme, set=set_name, subset=subset, p=float(p), warn=float(warn), p_ref=rate))
    predictions = pd.DataFrame(records, columns=PREDICTION_COLUMNS)
    predictions.attrs["fit_failures"] = failures
    predictions.attrs["convergence_failure_folds"] = sum(item["reason"].startswith("optimizer_failure") for item in failures)
    return predictions


def frozen_parameters(data):
    """S1 공통 개발집합의 2019 동결 및 전체 개발 매개변수를 구한다."""
    # 지도와 주 비교의 척도·발생률이 같은 학습 사상에서 나오게 한다.
    data = prepare_table(data)
    data = _eligible(data[data.role.eq("development") & data.label.isin([0, 1])], "M_int", "common")
    result = {}
    for name, training in (("V3", data[data.t0.lt(pd.Timestamp("2020-01-01"))]), ("all_dev", data)):
        result[name] = {model: _fit(training, model, logit_prior.fit, logit_prior.fit_intercept_only)
                        for model in ("M_fc24", "M_fc6", "M_obs", "M_int")}
        result[name]["B_clim"] = float(training.label.mean()) if len(training) else np.nan
    return result


def _interval(row, name, statistic, arrays, n_bootstrap, seed):
    """한 지표의 추정치·구간·정의 불가 횟수를 행에 추가한다."""
    # 모든 지표는 같은 사상 배열 묶음으로 재표집한다.
    interval = em.paired_bootstrap(statistic, arrays, n=n_bootstrap, seed=seed)
    row[name] = interval["estimate"]
    row.update({f"{name}_{key}": interval[key] for key in ("lo", "hi", "n_valid", "n_undefined")})


def summarize(predictions, *, n_bootstrap=2000, seed=20260926):
    """짝지은 기준 예측과 두 확률 임계의 지표·구간을 집계한다."""
    # 각 행의 모형별 학습 발생률을 그대로 짝지어 pooled BSS와 붓스트랩에 쓴다.
    result = []
    for group_key, group in predictions.groupby(GROUP_COLUMNS, sort=True):
        base = dict(zip(GROUP_COLUMNS, group_key))
        finite = np.isfinite(group.p) & np.isfinite(group.label)
        base.update(n=int(finite.sum()), n_pos=int(group.loc[finite, "label"].sum()),
                    n_total=len(group), n_missing=int((~finite).sum()))
        p, y, ref = (group[column].to_numpy(dtype=float) for column in ("p", "label", "p_ref"))
        base["n_bss"] = int((np.isfinite(p) & np.isfinite(y) & np.isfinite(ref)).sum())
        _interval(base, "brier", em.brier, [p, y], n_bootstrap, seed)
        _interval(base, "bss", em.bss_pooled, [p, y, ref], n_bootstrap, seed)
        _interval(base, "auc", em.auc, [p, y], n_bootstrap, seed)
        probability_model = group_key[0].startswith("M_") or group_key[0] == "B_clim"
        thresholds = ["0.5", "train_rate"] if probability_model else ["rule"]
        for threshold in thresholds:
            row = dict(base, threshold=threshold)
            warn = np.where(np.isfinite(p), p >= 0.5, np.nan) if threshold == "0.5" else group.warn.to_numpy(dtype=float)
            row.update(em.categorical(warn, y))
            for metric in ("pod", "far", "csi"):
                _interval(row, metric, lambda w, labels, key=metric: em.categorical(w, labels)[key], [warn, y], n_bootstrap, seed)
            row["pod_cp_lo"], row["pod_cp_hi"] = em.clopper_pearson(row["hits"], row["hits"] + row["misses"])
            result.append(row)
    columns = [*GROUP_COLUMNS, "n", "n_pos", "n_total", "n_missing", "n_bss", "threshold",
               "hits", "misses", "false_alarms", "correct_negatives", "pod_cp_lo", "pod_cp_hi"]
    for metric in ("brier", "bss", "auc", "pod", "far", "csi"):
        columns.extend([metric, *[f"{metric}_{suffix}" for suffix in ("lo", "hi", "n_valid", "n_undefined")]])
    return pd.DataFrame(result, columns=columns)


def reliability_table(predictions):
    """모든 모형·검증·집합·부분집합의 고정 신뢰도표를 연결한다."""
    # 예측이 전혀 없어도 저장 파일의 열 이름을 유지한다.
    tables = []
    for key, group in predictions.groupby(GROUP_COLUMNS, sort=True):
        table = em.reliability(group.p, group.label)
        for column, value in zip(GROUP_COLUMNS, key):
            table[column] = value
        tables.append(table)
    return pd.concat(tables, ignore_index=True) if tables else pd.DataFrame(columns=[*GROUP_COLUMNS, "left", "right", "n", "mean_p", "observed"])


def primary_endpoint_1(metrics):
    """V1·common·S1의 M_fc24 pooled BSS 하한으로 주 판정한다."""
    # 정의 불가와 하한 미통과를 정보 부재의 증거로 해석하지 않는다.
    selected = metrics if metrics.empty else metrics[metrics.model.eq("M_fc24") & metrics.scheme.eq("V1_loso") &
                                                    metrics["set"].eq("common") & metrics.subset.eq("S1")]
    estimate, lo, hi = (np.nan, np.nan, np.nan) if selected.empty else tuple(selected.iloc[0][column] for column in ("bss", "bss_lo", "bss_hi"))
    passed = bool(np.isfinite(lo) and lo > 0)
    return dict(estimate=float(estimate), lo=float(lo), hi=float(hi), passed=passed, criterion="하한 > 0",
                statement="이 조건부 모집단에서 예보가 사상 발생에 기후값 이상의 정보를 준 증거" if passed else "하한 > 0 기준 미충족: 정보 없음의 증명이 아님")
