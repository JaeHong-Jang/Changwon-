"""개발 사상과 침수 덩어리를 보존하는 누수 방지 분할을 만든다."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.data.uncertainty import spatial_clusters


@dataclass
class Fold:
    """전역 행 번호와 학습·시험 라벨을 보관한다."""

    name: str
    train: np.ndarray
    test: np.ndarray
    train_y: np.ndarray
    test_y: np.ndarray


def block_groups(points: np.ndarray, labels: np.ndarray, block_m: float = 2000) -> np.ndarray:
    """같은 양성 덩어리가 걸친 정사각 블록들을 하나의 그룹으로 합친다."""
    _, block = np.unique(np.floor(points / block_m).astype(int), axis=0, return_inverse=True)
    parent = np.arange(block.max() + 1)

    def root(i: int) -> int:
        """합쳐진 블록의 대표 번호를 찾는다."""
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    positive = np.flatnonzero(labels)
    clusters = spatial_clusters(points[positive, 0], points[positive, 1])
    for cluster in np.unique(clusters):
        members = np.unique(block[positive[clusters == cluster]])
        for member in members[1:]:
            parent[root(int(member))] = root(int(members[0]))
    return np.array([root(int(b)) for b in block])


def group_assignment(labels: np.ndarray, groups: np.ndarray, n_splits: int, seed: int = 42) -> np.ndarray:
    """양성 수를 고려하면서 공간 그룹을 fold에 통째로 배정한다."""
    from sklearn.model_selection import StratifiedGroupKFold

    if np.unique(groups).size < n_splits:
        raise ValueError("공간 그룹 수가 fold 수보다 적다")
    assignment = np.full(len(labels), -1, dtype=int)
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for number, (_, test) in enumerate(cv.split(np.zeros(len(labels)), labels, groups)):
        assignment[test] = number
    return assignment


def outside_buffer(
    points: np.ndarray, test_points: np.ndarray, *, block_m: float = 2000,
    buffer_m: float = 300, cell_m: float = 100,
) -> np.ndarray:
    """시험 블록에서 격자 사각형까지 거리가 버퍼보다 큰 행만 남긴다."""
    blocks = np.unique(np.floor(test_points / block_m), axis=0)
    keep = np.ones(len(points), dtype=bool)
    for block in blocks:
        delta = np.maximum(np.abs(points - (block + 0.5) * block_m) - (block_m + cell_m) / 2, 0)
        keep &= np.einsum("ij,ij->i", delta, delta) > buffer_m**2
    return keep


def spatial_folds(
    points: np.ndarray, labels: np.ndarray, *, n_splits: int = 5,
    groups: np.ndarray | None = None, buffer_m: float = 300,
) -> list[Fold]:
    """덩어리를 보존한 블록 분할에서 시험 블록 주변 학습 격자를 제외한다."""
    labels = np.asarray(labels, dtype=bool)
    groups = block_groups(points, labels) if groups is None else groups
    assignment = group_assignment(labels, groups, n_splits)
    folds = []
    for number in range(n_splits):
        test = np.flatnonzero(assignment == number)
        train = np.flatnonzero(assignment != number)
        train = train[outside_buffer(points[train], points[test], buffer_m=buffer_m)]
        folds.append(Fold(str(number), train, test, labels[train], labels[test]))
    return folds


def event_folds(events: np.ndarray, names: list[str]) -> list[Fold]:
    """뺀 사상 양성은 학습에서 전부 제외하고 공통 음성은 후속 교차 예측에 넘긴다."""
    events = np.asarray(events, dtype=bool)
    negative = ~events.any(axis=1)
    folds = []
    for i, name in enumerate(names):
        held = events[:, i]
        train = np.flatnonzero(~held)
        test = np.flatnonzero(held | negative)
        # 공통 음성은 여기서 후보 집합이며 실제 fit 전에 반드시 분리한다.
        folds.append(Fold(name, train, test, events[train].any(axis=1), held[test]))
    return folds


def crossfit_event(fold: Fold, assignment: np.ndarray) -> list[Fold]:
    """LOEO 공통 음성도 시험 그룹별로 학습에서 빼서 실제 OOF 예측을 만든다."""
    parts = []
    for group in np.unique(assignment):
        train_mask = (assignment[fold.train] != group) | fold.train_y
        test_mask = (assignment[fold.test] == group) | fold.test_y
        part = Fold(f"{fold.name}.{group}", fold.train[train_mask], fold.test[test_mask],
                    fold.train_y[train_mask], fold.test_y[test_mask])
        if np.intersect1d(part.train, part.test).size:
            raise ValueError("LOEO 학습·시험 행 중복")
        parts.append(part)
    return parts


def past_flood_score(points: np.ndarray, train: np.ndarray, train_y: np.ndarray, test: np.ndarray) -> np.ndarray:
    """학습 양성 격자 중심점만으로 최근접 거리의 음수를 계산한다."""
    from scipy.spatial import cKDTree

    source = train[np.asarray(train_y, dtype=bool)]
    if np.intersect1d(source, test).size:
        raise ValueError("시험 격자가 과거 침수 근접도 원천에 포함됐다")
    if not len(source):
        return np.zeros(len(test))
    distance, _ = cKDTree(points[source]).query(points[test])
    return -distance
