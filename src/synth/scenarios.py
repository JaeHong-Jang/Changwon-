"""M4S 시나리오 격자 115개 (docs/q1/M4S_protocol.md §2): 묶음 A 주·B 사상·C1 크기 척도·C2 분포 모양·D 기본 탐지력."""

from __future__ import annotations

from dataclasses import asdict, dataclass

SEED = 20260927
REPLICATES = 200
BETAS = (-1.0, -0.5, 0.0, 0.5, 1.0)
BETAS_B = (-0.5, 0.0, 0.5)


@dataclass(frozen=True)
class Scenario:
    """생성 인수 한 벌 (shape 는 lognormal 의 σ 또는 pareto 의 α)."""

    no: int
    block: str
    dist: str = "lognormal"
    median: float = 5000.0
    shape: float = 1.5
    beta: float = 0.0
    n_obj: int = 200
    n_events: int = 1
    counts: str = "equal"
    upsilon: float = 0.0
    mu0: float = 0.95
    tau: float = 0.5

    def row(self) -> dict:
        """표 한 행."""
        return asdict(self)


def grid() -> list[Scenario]:
    """절차 §2 표 순서(묶음 → 앞 인수가 바깥 고리)로 번호를 매긴 시나리오 목록."""
    # 묶음마다 인수 조합을 차례로 만든다
    specs = [dict(block="A", shape=s, beta=b, n_obj=n)
             for s in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0) for b in BETAS for n in (30, 200)]
    specs += [dict(block="B", n_events=e, counts=c, upsilon=u, beta=b, n_obj=50)
              for e in (4, 10) for c in ("equal", "skewed") for u in (0.0, 0.5) for b in BETAS_B]
    specs += [dict(block="C1", median=m, beta=b) for m in (500.0, 2000.0, 20000.0, 50000.0) for b in BETAS_B]
    specs += [dict(block="C2", dist="pareto", shape=a, beta=b) for a in (1.0, 1.5, 2.0) for b in BETAS_B]
    specs += [dict(block="D", mu0=m, beta=b) for m in (0.55, 1.45) for b in BETAS]
    return [Scenario(no=i, **spec) for i, spec in enumerate(specs)]
