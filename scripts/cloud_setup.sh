#!/usr/bin/env bash
# 클라우드 세션 환경 준비: LFS 원본, 가상환경, 로컬 전용이던 산출물 복원, API 키 확인 (AGENTS §8).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

# LFS 를 쓰는 브랜치(develop)면 LFS 객체를 받는다: 기본은 Q1 필요분 약 145 MB, FULL_LFS=1 이면 kma 외 전부.
# cloud-base 브랜치는 LFS 없이 일반 git 파일만 담으므로 이 단계를 건너뛴다 (GitHub LFS 비용 회피).
if grep -q 'filter=lfs' .gitattributes 2>/dev/null; then
  if ! command -v git-lfs >/dev/null 2>&1; then
    (sudo apt-get update -qq && sudo apt-get install -y -qq git-lfs) || apt-get install -y -qq git-lfs
  fi
  git lfs install --local >/dev/null
  if [ "${FULL_LFS:-0}" = 1 ]; then
    git lfs pull --exclude="data/raw/kma/**"
  else
    git lfs pull --include="artifacts/**,data/raw/flood_traces/**,data/raw/dem/**,data/raw/river/**,data/raw/rivers/**,data/raw/shelters/**,data/external/**"
  fi
fi

# 가상환경과 의존성 (shap 은 설명 분석용 추가)
# rasterio>=1.5 는 Python 3.12 이상이 필요하다 (3.11 에서 설치 실패, M1 세션 보고)
PYBIN=$(command -v python3.12 || command -v python3.13 || command -v python3)
"$PYBIN" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt shap

# 코드가 읽는 경로(.omc/, data/processed/)로 동결 모델·가공 스냅샷을 복원하고 해시를 확인한다
mkdir -p .omc data/processed/layers data/processed/features
rm -rf .omc/benchmark .omc/uncertainty
cp -r artifacts/frozen/benchmark artifacts/frozen/uncertainty .omc/
(cd artifacts/processed_snapshot && sha256sum -c --quiet SHA256SUMS)
cp artifacts/processed_snapshot/layers/*.gpkg data/processed/layers/
cp artifacts/processed_snapshot/features/*.parquet data/processed/features/

# API 키는 클라우드 환경변수로 받는다 (.env 는 올라오지 않는다)
for k in SAFETYDATA_API_KEY KMA_APIHUB_KEY VWORLD_API_KEY; do
  [ -n "${!k:-}" ] || echo "경고: 환경변수 $k 가 없다 — 해당 API 를 쓰는 작업(M5 등)은 실패한다"
done
echo "준비 완료: PY=.venv/bin/python"
