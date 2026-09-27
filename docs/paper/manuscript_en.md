# Auditing a frozen urban flood index with administrative flood traces: a gate failure that holds across 32 labelling settings and an exact decomposition of cell-level AUC

> **Draft v0.1 (2026-09-27), task M7.** Target journal: *Natural Hazards and Earth System Sciences* (NHESS), research article.
> Status: working draft for the authors. Not submitted. Author list, affiliations, acknowledgements and funding are placeholders.
> Every number is traced to a run ID in `docs/paper/numbers_provenance.md`. Rules for claims, wording and citations: `docs/q1/M7_protocol.md`.
> Citation markers `[미확인: …]` flag methods references whose DOI could not be checked against Crossref from the cloud session; they must be verified or removed before submission.

**Authors:** [Author 1]¹, [Author 2]¹ — ¹[Affiliation]
**Correspondence:** [name, e-mail]

---

## Short summary (≤ 500 characters, NHESS submission field)

We froze a guideline-based urban flood index for Changwon, South Korea, and scored it on flood traces obtained after freezing. It failed its pre-specified gate, and the failure held under all 32 combinations of label rule and grid size. We show that cell-level AUC is exactly a weighted mean of per-polygon contributions, explain why it can differ from polygon-level AUC by more than 0.1, and confirm the mechanism in 115 synthetic scenarios.

## Abstract

Urban flood indices built from guideline indicators are rarely tested against observed floods, and when they are, the result depends on how flood-trace polygons are turned into grid labels. We audited a guideline-structured flood index (L1) for Changwon, South Korea, on a 100 m grid of 75 400 cells. A pass/fail gate (cell-level AUC ≥ 0.70 and top-20 % capture ≥ 0.50) was recorded and the index formula frozen before the city released flood traces for four events in 2022–2024. On these traces L1 scored a cell-level AUC of 0.436 and a capture of 0.073, failing the gate. The pooled failure persisted in all 32 combinations of eight label rules and four grid sizes (100–1000 m), and capture never exceeded 0.412. The median of event-wise scores, however, passed at the reference setting; one event supplied 1254 of the 1267 pooled positive cells. We show that cell-level AUC is exactly a weighted mean of per-polygon contributions, weighted by the positive-cell mass each polygon creates. The gap between cell-level (0.436) and polygon-level (0.712) AUC splits into size weighting (−0.198) and polygon loss (−0.078). Agricultural polygons carried 97.6 % of the weight, and the effective number of polygons was 25.7 of 196. In 115 synthetic scenarios, systematic gaps of 0.1 or more arose only when polygon sizes were dispersed and detectability depended on size, and a closed-form expression predicted their sign and magnitude. A slope-only baseline matched learned terrain models (median event AUC 0.872 vs. 0.855), so we do not claim that learned models add skill. We recommend reporting cell- and polygon-level scores together, treating events as the sampling unit and publishing the weight concentration behind any cell-level AUC.

---

## 1 Introduction

Composite indices are a common way to map urban flood susceptibility and vulnerability. They combine standardised indicators of exposure and sensitivity, often following a national guideline, and produce a ranked map that planners can use. Their external validation is uncommon: a systematic review of flood vulnerability indices found that only 13.7 % of 95 studies validated the index against an outcome (Moreira et al., 2021), and the construct validity of related social vulnerability indices has been questioned when tested against loss data (Fekete, 2009; Tate, 2012; Rufat et al., 2019; Bakkensen et al., 2017). Composite-index methodology itself warns that indicator choice, normalisation, weighting and aggregation can change rankings (Saisana et al., 2005; Greco et al., 2019). Calls for more usable and credible flood hazard assessments stress that the evaluation must match the purpose of the map (Merz et al., 2024), and national-scale hazard data have been shown to be unfit for urban risk decisions without local testing (Schubert et al., 2024).

When flood susceptibility maps are evaluated, the evaluation design strongly affects the numbers. Random cross-validation of spatial data gives higher AUC than spatial or temporal splits (Brenning, 2005; Roberts et al., 2017; Meyer et al., 2018; Schratz et al., 2019; Ploton et al., 2020). In flood studies, a spatio-temporal cross-validation of pluvial flood events in Venice found common procedures over-optimistic (Zanetti et al., 2022), a year-wise holdout in south-east Texas scored lowest on the most extreme events (Mobley et al., 2021), and models for Seoul and Berlin have been tested on a later year or outside the training area (Lee et al., 2017; Seleem et al., 2022). Binary pattern measures used to compare flood maps with observations also depend on how the comparison is set up (Stephens et al., 2014). Flood inventories used as labels are presence-only records: cells without a recorded flood are unlabelled rather than confirmed dry, so the AUC measures the ranking of recorded against unrecorded locations, and absolute probabilities are not identifiable from such data alone (Hirzel et al., 2006; Phillips et al., 2009; Phillips and Elith, 2013; Bekker and Davis, 2020).

A further design choice has received less attention in urban flood work: how inventory polygons are converted into grid labels, and whether the score is computed per grid cell or per flood polygon. Converting polygons to cells is a change of support (Dark and Bram, 2007). In landslide susceptibility, positional errors and systematic incompleteness of inventories and the way landslide polygons are sampled change estimated performance (Hussin et al., 2016; Steger et al., 2016, 2017; Ozturk et al., 2021), and for Earth-observation flood maps the sampling design, the flooded-area proportion and the choice of metric change the conclusions of a validation (Landwehr et al., 2024). The weights implied by cell-level scoring are rarely written down, so it is hard to tell which part of an inventory decides a cell-level AUC.

Here we report an audit of a guideline-based index for the city of Changwon, South Korea. The index (L1) was frozen before the city released flood traces for four events in 2022–2024, and a gate had been recorded before that release. The index failed the gate. We ask three questions:

1. Does the gate failure depend on the label rule or grid size used to turn trace polygons into cell labels?
2. Why do cell-level and polygon-level AUC differ so much for the same index and events, and is the mechanism specific to Changwon?
3. What do trivial terrain baselines and event-level uncertainty imply for learned models fitted to the same records?

Our contributions are (i) a check that the gate failure holds across 32 labelling settings, reported together with the event-wise summary that passes; (ii) an exact identity that writes cell-level AUC as a weighted mean of per-polygon contributions, a three-term decomposition of the cell–polygon gap and a covariance form of its main term; (iii) a synthetic demonstration, with predictions fixed before computation, that the gap requires both size dispersion and size-dependent detectability; and (iv) a set of trivial-baseline and event-level checks that led us to withdraw an earlier claim that learned terrain models add skill.

The status of the evidence matters for how these results can be read. The 2022–2024 events occurred before the index was designed; only the release of their traces came after the freeze. The holdout assessment of L1 is therefore an evaluation of a pre-frozen index on independent events obtained after freezing, not a prospective or pre-registered validation. All other analyses on the 2022–2024 traces (label-rule sensitivity, baselines, event-level synthesis, learned models) were designed after the L1 result was known and are labelled post hoc throughout. For each of these analyses the scores, strata and decision rules were written and committed to the project repository before computation (Sect. 3.8).

## 2 Study area and data

### 2.1 Study area and grid

Changwon is a coastal city of about 747 km² in south-eastern Korea. The analysis grid is the national statistical 100 m grid (SGIS) clipped to the city, 75 400 cells in the Korean projected coordinate system EPSG:5179. Terrain covariates come from a public 90 m DEM (2025 release) resampled bilinearly to the 100 m grid; because of this DEM resolution we do not analyse grids finer than 100 m.

### 2.2 The frozen index L1

L1 follows the structure of the national guideline for urban climate-change disaster vulnerability analysis (MOLIT, 2024 revision) [미확인: grey literature, no DOI]: vulnerability is a function of climate exposure and urban sensitivity on a 100 m grid, each built as a sum of standardised indicators. Lee and Kang (2018) compared guideline-based urban flood vulnerability results with observed floods in Busan.

- **Exposure (four indicators).** Mean annual maximum hourly rainfall, mean annual count of hours ≥ 30 mm, and the mean of the five largest non-overlapping 3 h and 24 h totals, computed at 29 gauges for 2015–2024 and interpolated by inverse-distance weighting (power chosen per indicator by leave-one-out RMSE).
- **Sensitivity (eight indicators, signs fixed a priori).** Relative elevation (−), slope (−), topographic wetness index TWI (+), impervious fraction (+), proximity to OSM river centre lines (+), proximity to culverted streams (+), the city's 100-year pluvial flood-map depth (+) and location within 1 km of a drainage pumping station (+).
- **Aggregation.** Each indicator is winsorised at the 1st and 99th percentiles, z-standardised and summed with its sign and equal weights; L1 = min–max(Z_exposure + Z_sensitivity) ∈ [0, 1].

The gate — cell-level AUC ≥ 0.70 and top-20 % area capture ≥ 0.50 — was first recorded in the project's methods specification on 19 August 2026 and set as code constants on 7 September 2026. The L1 formula was last changed on 8 September 2026. On six development events (Sect. 2.3) L1 scored a cell-level AUC of 0.750 [95 % cluster-bootstrap interval 0.633, 0.863] and a capture of 0.544, and passed the gate on 16 September 2026, before the 2022–2024 traces arrived.

### 2.3 Flood traces

Flood traces are polygons of observed inundation recorded by public authorities after heavy-rain events (Table 1).

- **Development events.** Five events from the national flood-trace service of the Ministry of the Interior and Safety (2006, 2012, 2014, 2016, 2019; 125 polygons) and one event supplied by the city (July 2025; 18 polygons). Of the 143 dated development polygons, 142 intersect the analysis grid. Two further development polygons have no date and are excluded from event-wise analyses.
- **Holdout events.** Traces for 6 September 2022 (typhoon Hinnamnor, 5 polygons), 10 August 2023 (typhoon Khanun, 3), 24 July 2024 (5) and 20–21 September 2024 (183), released by the city on 24 September 2026 through an information-disclosure request. The union area is 9.55 km². Holdout polygons carry a land-use attribute: 57 urban, 119 agricultural and 20 unknown.

Cells not touched by a trace are unlabelled, not confirmed dry. We report AUC on observed labels and do not interpret it as a bound on true skill; it ranks recorded against unrecorded locations and is not a map-accuracy estimate in the design-based sense (Wadoux et al., 2021).

**Table 1.** Events, polygons and positive cells under the reference label rule (a cell is positive if trace polygons of the event cover more than 10 % of it; 100 m grid). Clusters are connected groups of positive cells used for resampling.

| Event | Role | Polygons | Positive cells | Clusters |
|---|---|---:|---:|---:|
| 2006 | development | 19 | 107 | 3 |
| 2012 | development | 31 | 206 | 14 |
| 2014 | development | 47 | 132 | 13 |
| 2016 | development | 21 | 170 | 6 |
| 2019 | development | 7 | 56 | 3 |
| 2025-07 | development | 18 | 25 | 14 |
| 2022-09-06 | holdout | 5 | 0 | 0 |
| 2023-08-10 | holdout | 3 | 18 | 3 |
| 2024-07-24 | holdout | 5 | 0 | 0 |
| 2024-09-20 | holdout | 183 | 1254 | 52 |
| Pooled holdout | holdout | 196 | 1267 | 54 |

*Source: run `m4_20260926T170511Z_1edf87c`, `events.csv`.*

Two of the four holdout events leave no positive cell under the 10 % rule, and one event supplies 1254 of the 1267 pooled positive cells. Any cell-level holdout statistic is therefore close to a statistic of the September 2024 event.

### 2.4 Chronology and input vintages

We reconstructed a 42-entry chronology from run records, commits and file metadata (Appendix D). The key order is: gate recorded (19 August 2026) → L1 formula last changed (8 September) → development gate passed (16 September) → holdout traces received (24 September) → holdout first read by a unit-test run (by 18:18 KST on 24 September, no scoring) → first official scoring (18:38 KST). The candidate feature sets of the learned models (Sect. 3.1) were chosen after a diagnostic look at the holdout for which no time stamp exists, and the random-forest configuration was re-selected about 10 min after the first official scoring following a review that found fold leakage. The learned models are therefore post hoc, and the fold leakage is an example of the broader leakage problems documented for machine-learning-based science (Kapoor and Narayanan, 2023).

All inputs describe the city in 2024–2025, later than the 2006–2019 development events. The rainfall-climatology period (2015–2024) contains the holdout years. This is not label leakage, but it is a mismatch in time that we disclose.

## 3 Methods

### 3.1 Scores

We score ten fields on every event (signs fixed before computation so that larger means more flood-prone):

- **Trivial baselines:** negative slope; negative relative elevation; TWI; impervious fraction; negative height above nearest drainage (HAND; Nobre et al., 2011) computed on the 100 m grid with OSM rivers as drainage (main definition) or cells with flow accumulation ≥ 100 cells (variant). HAND uses priority-flood depression filling with an ε-gradient for flow directions [미확인: Barnes et al. 2014, Priority-Flood].
- **The frozen index** L1 and its **sensitivity axis** alone (Z_sensitivity).
- **Learned models:** a random forest (RF-F1: eight sensitivity indicators, maximum depth 4, minimum leaf size 400) and a ridge-penalised logistic regression on the same features. Each is re-fitted, for every test event, on development events that occurred earlier ("walk-forward"); 2006 has no earlier event and no learned score.

### 3.2 Label rules, grid sizes and evaluation units

For event e and cell i let f_i be the fraction of the cell covered by the union of the event's polygons. A label rule assigns a positive mass p_i ∈ [0, 1] and a negative mass q_i = 1 − p_i. We use eight rules: `any` (f_i > 0), `f01`, `f10` (reference; f_i > 0.10), `f25`, `f50` (thresholds on f_i), `center` (cell centre inside a polygon), `rep_point` (the cell containing each polygon's representative point) and `soft` (p_i = f_i). Grids of 200, 500 and 1000 m are built by aggregating 100 m cells in absolute EPSG:5179 coordinates; coarse-cell scores are means of the 100 m scores, so that only the evaluation changes, not the scores. Eight rules × four sizes give 32 settings. Learned models are always trained on 100 m `f10` labels.

- **Cell-level AUC** is the weighted Mann–Whitney statistic
  A = Σ_i Σ_j p_i q_j H(s_i − s_j) / (Σ_i p_i Σ_j q_j), with H(x) = 1, ½, 0 for x > 0, = 0, < 0.
  For binary rules this is the usual AUC of positive cells against all other cells.
- **Top-20 % capture** is the share of positive mass in the highest-scoring 20 % of the scored area.
- **Polygon-level (object) AUC** gives each polygon one vote. Polygon k has value Ã_k = Σ_i a_ki G(s_i) / Σ_i a_ki, where a_ki is its overlap area with cell i and G is the mid-rank cumulative distribution of scores over background cells that no trace of any event touches. The object AUC Ã is the mean of Ã_k.
- **Cluster AUC** uses connected clusters of positive cells as resampling units; 95 % intervals are cluster-bootstrap percentiles.

### 3.3 Gate verdicts

The gate margin is m = min(A − 0.70, capture − 0.50); the gate is passed when m ≥ 0. Thresholds were not lowered in any analysis.

- **V1 (pooled holdout):** the margin on the union of all holdout traces, the unit of the original gate.
- **V2 (event median):** the margin computed from the medians of cell-level AUC and capture over the test events (development and holdout) that have at least five positive cells and a value for all ten scores.
- A **flip** is a change of pass/fail relative to the reference setting (`f10`, 100 m). A **material flip** is a flip with |m| ≥ 0.02 in both settings.
- Decision rule, fixed before computation: if L1 had a material V1 or V2 flip under a conventional rasterisation choice at 100 m (`any`, `center` or `f50`), the claim "changing only the rasterisation rule flips the L1 verdict" would be supported; if material flips occurred only in other settings (non-conventional rules or coarser grids), it would be partially supported; if there were none, it would be dropped.

### 3.4 An exact decomposition of cell-level AUC

Let F(s) = Σ_j q_j H(s − s_j) / Σ_j q_j be the mid-rank distribution of negative mass, so that A = Σ_i p_i F(s_i) / Σ_i p_i. Split the positive mass of cell i among the polygons that overlap it in proportion to overlap area, π_ki = a_ki / Σ_k′ a_k′i. Define for polygon k

$$W_k = \sum_i p_i \pi_{ki}, \qquad A_k = \frac{1}{W_k}\sum_i p_i \pi_{ki} F(s_i) \quad (W_k > 0).$$

Because Σ_k π_ki = 1,

$$A = \sum_k w_k A_k, \qquad w_k = \frac{W_k}{\sum_{k'} W_{k'}} . \tag{1}$$

Cell-level AUC is thus a weighted mean of per-polygon contributions A_k, and the weight of a polygon is the positive-cell mass it creates. A polygon that creates no positive cell (it is "lost" under the rule) has zero weight. Under `soft`, w_k is proportional to the polygon's de-duplicated flooded area.

Let S be the surviving polygons (W_k > 0 and Ã_k finite) and K the polygons with a finite Ã_k. The gap to the object AUC splits exactly into three terms:

$$A - \tilde A = \underbrace{\Big[A - \overline{A_k}^{S}\Big]}_{\text{size weighting}} + \underbrace{\Big[\overline{A_k}^{S} - \overline{\tilde A_k}^{S}\Big]}_{\text{within polygon}} + \underbrace{\Big[\overline{\tilde A_k}^{S} - \overline{\tilde A_k}^{K}\Big]}_{\text{loss}} . \tag{2}$$

The within-polygon term compares positive cells against the gate background with all overlapped cells against the untouched background. We summarise concentration by the Kish effective number of polygons n_eff = 1 / Σ w_k².

When all positive mass is assigned to surviving polygons, the size-weighting term has a covariance form (Appendix A):

$$A - \overline{A_k}^{S} = \rho_S(\tilde w, A)\;\mathrm{sd}_S(A)\;\sqrt{n_S/n_{\mathrm{eff},S} - 1}, \tag{3}$$

the product of the correlation between weight and contribution, the spread of contributions and a concentration factor. If contributions are unrelated to weight, the expected size-weighting term is zero, but its variance grows as n_eff falls.

For log-normal polygon areas (log-area standard deviation σ) and a detectability that shifts linearly with standardised log-area, μ_k = μ0 + βζ_k + τε_k, area weighting tilts ζ from N(0, 1) to N(σ, 1), which gives the population gap (Appendix A)

$$\Delta^*(\sigma, \beta) = \Phi\!\left(\frac{\mu_0 + \beta\sigma}{D}\right) - \Phi\!\left(\frac{\mu_0}{D}\right), \qquad D = \sqrt{2 + \beta^2 + \tau^2}. \tag{4}$$

Δ* is zero if either σ or β is zero and takes the sign of β. It assumes area weights (the `soft` rule), no truncation and many polygons.

Identity (1) was checked against an independent computation (`sklearn.metrics.roc_auc_score` on replicated, mass-weighted samples) for every event, setting and score; the implementation stops if the absolute difference exceeds 10⁻⁹.

### 3.5 Synthetic demonstration

To test whether the Changwon gap is a general consequence of Eqs. (1)–(4), we generated synthetic inventories on a 200 × 200 grid of 100 m cells with a spatially autocorrelated standard-normal background score (Gaussian smoothing, σ = 2 cells). Polygons are ellipses with log-normal or Pareto areas truncated to 50 m²–10 km², placed at random, with detectability μ_k = μ0 + βζ_k + τε_k + υη_e(k) (τ = 0.5); cells covered by polygon k receive score z_i + μ_k. We ran 115 scenarios (log-area spread σ = 0.5–3, coupling β = −1 to 1, 30 or 200 polygons, multi-event inventories, median areas 500–50 000 m², Pareto tails, base detectability μ0 = 0.55–1.45) with 200 replicates each, scored with the eight label rules at 100 m. The predictions and decision rule were committed before any scenario was computed:

- P1: identity (1) and covariance form (3) hold to 10⁻⁹;
- P2: without coupling (β = 0), the median gap is < 0.03 in absolute value (or its order-statistic interval covers 0) for `f10` and `soft`;
- P3/P3′: where |Δ*| ≥ 0.15, the gap is "wide" (P(|A − Ã| ≥ 0.1) ≥ 0.5, required for `f10` only where |Δ*| ≥ 0.20) and has the sign of β; where |Δ*| < 0.06 it is not "wide".

Some design values (the upper σ, the 5000 m² median area and μ0 = 0.95) were set after seeing the Changwon result so that the scenarios cover its range; this is disclosed in the protocol. A post hoc anchor places Changwon's events in the synthetic space by estimating σ̂ and β̂ from observed polygon areas and Ã_k values.

### 3.6 Trivial baselines and hard negatives

We tested whether learned models add anything over single terrain variables. Topographic indices are established low-cost indicators of flood-prone or pluvial flooding locations (Samela et al., 2017; Kelleher and McPhillips, 2020), so they are the natural trivial baselines. The pre-specified rule was: over the test events with a learned score and at least five positive cells, if the median cell-level AUC of slope alone is at least the median of RF-F1 minus 0.02, the claim that learned terrain models are better than trivial baselines is dropped. We also scored every field within harder backgrounds defined from grid attributes only: flat cells (slope ≤ 5°, fixed from the unlabelled slope distribution), urban cells (impervious fraction ≥ 0.5), an agricultural proxy (impervious < 0.1, slope ≤ 5°, inland water < 0.5; not checked against land-cover maps) and populated cells.

### 3.7 Event-level synthesis and nested temporal selection

Because grid cells within an event are not independent, the sampling unit for generalisation is the event. Classical paired AUC comparisons (DeLong et al., 1988) treat observations as independent, so we instead resampled clusters of positive cells within events and pooled across events. We pooled logit-transformed event AUCs with a random-effects model (REML with a modified Hartung–Knapp–Sidik–Jonkman interval [미확인: Hartung and Knapp 2001; Sidik and Jonkman 2002]), with standard errors back-calculated from the cluster-bootstrap intervals, and report 95 % prediction intervals and I². Paired differences between scores were pooled on the logit scale. The RF configuration had been chosen by cross-validation over all six development events, which lets information from later events enter earlier test events. We therefore repeated the walk-forward with configuration selection nested inside the earlier events (leave-one-event-out over the prior events, ranking configurations by the mean cluster AUC of the left-out events; 6 RF configurations in the main analysis and 24 configurations across four model families as a secondary analysis). The pre-specified rule was that the fixed configuration is optimistic if its median cell-level AUC exceeds the nested median by more than 0.02.

### 3.8 Protocol, provenance and reproducibility

Each analysis in Sects. 3.2–3.7 had a written protocol (scores, strata, metrics, decision rules) committed before its first computation; any change after computation is labelled post hoc and reported alongside the original rule. These time-stamped commits are internal records, not registrations with an external registry in the sense of Nosek et al. (2018), and they were written after the holdout L1 result was known. Runs record the git commit, a code hash and input hashes. Only the lead analyst ran code that reads the 2022–2024 traces; independent reviewers (different language models acting as read-only reviewers) recomputed decisive numbers without access to those traces. The official holdout scoring was repeated from a clean commit (Sect. 4.6).

## 4 Results

### 4.1 The frozen index fails the gate in every labelling setting

On the pooled 2022–2024 traces L1 scored a cell-level AUC of 0.436 [0.386, 0.596], a cluster AUC of 0.603 [0.544, 0.661] and a top-20 % capture of 0.073, and failed both gate conditions. The city's own pluvial flood map scored 0.450 (capture 0.026) and a distance-to-past-traces baseline 0.532 (capture 0.205); both also failed.

Across the 32 settings, the V1 verdict for L1 was "fail" every time (Table 2). The margin ranged from −0.088 (`rep_point`, 100 m: AUC 0.694, capture 0.412) to −0.500. Both conditions failed in every setting, and capture was the more binding one. The V2 event-median verdict passed at the reference setting (median AUC 0.791, capture 0.558 over seven events) and at all eight rules at 100 m. It flipped materially in nine settings, all of which changed both the rule and the grid size (500 or 1000 m). Five of these nine rest on one to three events, mostly the September 2024 event alone. Under the pre-specified rule the claim is therefore only partially supported: no conventional rule at 100 m flipped the L1 verdict. More generally, changing only the rule at 100 m, or only the grid size under the reference rule, produced no material flip for any of the ten scores.

**Table 2.** L1 on the pooled holdout (V1) for eight label rules and four grid sizes: cell-level AUC / top-20 % capture. All 32 settings fail the gate (AUC ≥ 0.70 and capture ≥ 0.50). Bottom block: V2 margin (event-median gate), with the number of events in parentheses; negative values fail.

| Rule | 100 m | 200 m | 500 m | 1000 m |
|---|---|---|---|---|
| `any` | 0.477 / 0.124 | 0.515 / 0.160 | 0.569 / 0.224 | 0.621 / 0.255 |
| `f01` | 0.467 / 0.112 | 0.482 / 0.113 | 0.479 / 0.073 | 0.447 / 0.034 |
| **`f10`** | **0.436 / 0.073** | 0.432 / 0.056 | 0.420 / 0.038 | 0.397 / 0.000 |
| `f25` | 0.418 / 0.053 | 0.406 / 0.044 | 0.383 / 0.000 | 0.356 / 0.000 |
| `f50` | 0.394 / 0.030 | 0.370 / 0.009 | 0.361 / 0.000 | 0.341 / 0.000 |
| `center` | 0.400 / 0.042 | 0.394 / 0.037 | 0.393 / 0.021 | 0.339 / 0.000 |
| `rep_point` | 0.694 / 0.412 | 0.676 / 0.347 | 0.642 / 0.318 | 0.638 / 0.261 |
| `soft` | 0.403 / 0.044 | 0.398 / 0.036 | 0.391 / 0.019 | 0.383 / 0.010 |
| *V2 margin* | | | | |
| `any` | +0.055 (9) | +0.039 (9) | −0.064 (9) | −0.024 (9) |
| `f01` | +0.040 (8) | +0.022 (8) | −0.015 (7) | +0.103 (5) |
| **`f10`** | **+0.058 (7)** | +0.111 (5) | −0.011 (4) | +0.139 (3) |
| `f25` | +0.028 (6) | +0.060 (5) | +0.080 (3) | −0.500 (1) |
| `f50` | +0.069 (5) | +0.095 (5) | −0.500 (1) | −0.500 (1) |
| `center` | +0.016 (6) | +0.124 (5) | −0.071 (3) | −0.500 (1) |
| `rep_point` | +0.107 (8) | +0.026 (8) | −0.066 (8) | −0.052 (6) |
| `soft` | +0.063 (9) | +0.055 (9) | +0.032 (9) | +0.064 (9) |

*Source: run `m4_20260926T170511Z_1edf87c`, `verdicts.csv`. Reference setting in bold. The `f10`/100 m V1 values reproduce the official gate run `holdout_20260924T100939Z_ae9c122-dirty_cf388a23` (0.4357 / 0.0734). The `f10`/500 m and `f01`/500 m V2 flips are not material (|m| < 0.02).*

The AUC magnitude, unlike the verdict, moved a lot. At 100 m alone, L1's pooled AUC ranged from 0.394 (`f50`) to 0.694 (`rep_point`), a range of 0.300; across all 32 settings it ranged from 0.339 to 0.694. For the learned RF-F1 the corresponding 100 m range was 0.023. L1 ranked 8th–10th of the ten scores in all 32 V1 settings.

### 4.2 Cell-level AUC is a weighted mean of polygon contributions

Identity (1) held in all 2828 finite combinations of event, setting and score (maximum absolute error 1.6 × 10⁻¹⁵). For L1 on the pooled holdout, the reference cell-level AUC of 0.436 and the object AUC of 0.712 differ by −0.276. Of this, −0.198 is size weighting, −0.078 is the loss of polygons that leave no positive cell, and the within-polygon term is −0.000 (Table 3). Raising the threshold increases the loss term (−0.078 at `f10`, −0.116 at `f50`). `rep_point` gives each surviving polygon one cell, so its effective number of polygons (177.4) approaches the 196 polygons and its cell-level AUC (0.694) approaches the object AUC. `soft` weights by flooded area and has the largest size-weighting term (−0.306).

**Table 3.** Decomposition (Eq. 2) of L1 on the pooled holdout at 100 m. Object AUC is 0.712 for every rule.

| Rule | Cell AUC | Size weighting | Within polygon | Loss | n_eff | Surviving polygons |
|---|---:|---:|---:|---:|---:|---:|
| `any` | 0.477 | −0.228 | −0.006 | 0.000 | 36.3 | 196 |
| `f01` | 0.467 | −0.232 | −0.006 | −0.006 | 33.3 | 189 |
| **`f10`** | **0.436** | **−0.198** | **−0.000** | **−0.078** | **25.7** | **130** |
| `f25` | 0.418 | −0.189 | +0.001 | −0.106 | 22.4 | 106 |
| `f50` | 0.394 | −0.200 | −0.002 | −0.116 | 18.7 | 85 |
| `center` | 0.400 | −0.210 | −0.001 | −0.101 | 19.4 | 100 |
| `rep_point` | 0.694 | −0.015 | −0.003 | 0.000 | 177.4 | 196 |
| `soft` | 0.403 | −0.306 | −0.003 | 0.000 | 19.6 | 196 |

*Source: run `m4_20260926T170511Z_1edf87c`, `decomposition.csv`.*

The weights explain which floods decide the cell-level AUC (Table 4). Under the reference rule, the September 2024 event holds 98.8 % of the weight, agricultural polygons 97.6 % and polygons of 20 000 m² or more 89.8 %; the ten heaviest polygons hold 53.3 %. The 57 urban polygons hold 0.2 %, and only 7 of them survive the 10 % rule. Even under `any`, where every urban polygon survives, their share is 4.3 %. The polygon-level view tells the same story from the other side: the L1 polygon-level AUC (the mean Ã_k of the group) is 0.910 [0.879, 0.938] for urban and 0.608 [0.574, 0.642] for agricultural polygons (intervals from the official holdout run).

For other scores the sign of the size-weighting term is reversed. On the pooled holdout, slope, both HAND variants and TWI have size-weighting terms of +0.046 to +0.085 (cell AUC above object AUC): they rank the heavily weighted agricultural polygons highly, whereas L1 does not. For L1 on the development events, the cell–object gap under the reference rule is small (−0.012 to +0.053). The large L1 gap is a property of the September 2024 event.

**Table 4.** Weight shares under the reference rule (`f10`, 100 m, pooled holdout; shares are common to all scores).

| Group | Polygons | Surviving | Weight share | Mean Ã_k (L1) |
|---|---:|---:|---:|---:|
| 2024-09-20 | 183 | 127 | 0.988 | 0.707 |
| 2023-08-10 | 3 | 3 | 0.012 | 0.803 |
| 2022-09-06 | 5 | 0 | 0.000 | 0.915 |
| 2024-07-24 | 5 | 0 | 0.000 | 0.619 |
| Agricultural | 119 | 116 | 0.976 | 0.608 |
| Urban | 57 | 7 | 0.002 | 0.910 |
| Unknown | 20 | 7 | 0.022 | 0.764 |

*Source: `docs/q1/M4.md` (run `m4_20260926T170511Z_1edf87c`, `object_contrib.parquet`).*

Survival of polygons under each rule depends on polygon size relative to the cell (Table 5). Under the reference rule at 100 m, 66.3 % of holdout polygons survive, but only 9.3 % of those smaller than 500 m² (54 polygons) and 12.3 % of urban polygons (57). At 1000 m, even 26 % of holdout polygons of 20 000 m² or more disappear, because 20 000 m² is 2 % of a 1 km² cell. The development inventory is dominated by larger polygons, and 95.8 % of its 142 dated polygons survive at 100 m.

**Table 5.** Polygon survival under the reference threshold rule (`f10`) by area class and grid size. A polygon survives if at least one cell it overlaps is positive under the label of its own event (event-wise labels).

| Role | Area class (count) | 100 m | 200 m | 500 m | 1000 m |
|---|---|---:|---:|---:|---:|
| holdout | < 500 m² (54) | 0.093 | 0.000 | 0.000 | 0.000 |
| | 500–1000 m² (13) | 0.231 | 0.000 | 0.000 | 0.077 |
| | 1000–5000 m² (36) | 0.806 | 0.444 | 0.306 | 0.333 |
| | 5000–20 000 m² (39) | 1.000 | 0.949 | 0.590 | 0.462 |
| | ≥ 20 000 m² (54) | 1.000 | 1.000 | 0.926 | 0.741 |
| | all (196) | 0.663 | 0.546 | 0.429 | 0.362 |
| development | all dated (142) | 0.958 | 0.803 | 0.549 | 0.479 |

*Source: run `m4_20260926T170511Z_1edf87c`, `survival_summary.csv` (role groups `holdout` and `development`). With the pooled holdout label (union of all four events, `holdout_pooled`) one additional polygon of ≥ 20 000 m² survives at 500 m (0.944; all polygons 0.434); all other cells are identical. The 100 m holdout values match the earlier label audit `label_audit_holdout_20260924T104628Z_1b8106ba` (66.3 %, urban 12.3 %).*

### 4.3 The gap is general: size dispersion and size-dependent detectability together

In the synthetic experiment all three pre-specified predictions held, and the pre-specified verdict was "generality supported" (identity error ≤ 7.0 × 10⁻¹⁵; covariance form ≤ 1.4 × 10⁻¹² over 150 396 rows).

- **No coupling, no gap (P2).** With β = 0 all 21 scenarios had median gaps of at most 0.006 (`f10`) and 0.009 (`soft`) in absolute value.
- **Dispersion and coupling together, wide gap (P3, P3′).** All 15 scenarios with |Δ*| ≥ 0.15 had a wide gap with the sign of β under both `soft` and `f10`, and none of the 8 scenarios with |Δ*| < 0.06 did.
- **Eq. (4) predicts the size.** For σ ≤ 2 the realised `soft` gap was 0.94 of Δ* (median; range 0.86–1.06 over 24 scenarios) and the `f10` gap 0.74 (0.63–0.83), because counting cells concentrates weight less than counting area.

Table 6 shows the σ × β map for 200 polygons. At |β| = 1 the `f10` gap becomes wide from σ = 1.0, at |β| = 0.5 from σ = 1.5. Negative coupling (large polygons scored low, as for L1 in Changwon) produces larger gaps than positive coupling of the same size. At σ ≥ 2.5 the realised gap falls short of Δ*, as the protocol anticipated, because of area truncation and the finite sample maximum. As the median polygon area shrinks relative to the cell, the source of the gap shifts from size weighting to polygon loss with a similar total (−0.12 to −0.17 at σ = 1.5, β = −0.5).

**Table 6.** Synthetic gap A − Ã (median over 200 replicates; in parentheses P(|A − Ã| ≥ 0.1)) for the `f10` rule, 200 polygons, median area 5000 m², μ0 = 0.95, with the formula value Δ* (Eq. 4).

| | σ = 0.5 | 1.0 | 1.5 | 2.0 | 2.5 | 3.0 |
|---|---|---|---|---|---|---|
| Δ*, β = −1 | −0.102 | −0.212 | −0.321 | −0.421 | −0.506 | −0.573 |
| `f10`, β = −1 | −0.068 (0.00) | −0.145 (0.98) | −0.233 (1.00) | −0.313 (1.00) | −0.357 (1.00) | −0.347 (1.00) |
| `f10`, β = −0.5 | −0.036 (0.00) | −0.078 (0.14) | −0.126 (0.78) | −0.172 (0.94) | −0.197 (0.98) | −0.176 (0.96) |
| `f10`, β = 0 | −0.002 (0.00) | −0.000 (0.00) | −0.001 (0.00) | −0.002 (0.01) | −0.000 (0.02) | −0.006 (0.00) |
| `f10`, β = +0.5 | +0.032 (0.00) | +0.066 (0.02) | +0.104 (0.55) | +0.127 (0.87) | +0.138 (0.94) | +0.127 (0.90) |
| `f10`, β = +1 | +0.059 (0.00) | +0.121 (0.90) | +0.171 (1.00) | +0.204 (1.00) | +0.213 (1.00) | +0.200 (1.00) |

*Source: run `m4s_20260926T175809Z_3e8bc1c`, `summary_by_scenario.csv`. Figure 4 maps the same grid.*

A cell-level gate verdict can differ from the polygon-level verdict when the polygon-level AUC lies near the gate and the coupling points the other way. With μ0 = 1.45 (polygon-level gate passed in every replicate), β = −1 drove the cell-level pass rate to 0 %, a unit flip in every replicate, and β = −0.5 gave a flip rate of 0.62. With μ0 = 0.55 (polygon gate almost never passed), β = +0.5 produced cell-level passes in 95.5 % of replicates.

Two results limit these statements. First, the `rep_point` rule removes size weighting, but in landscapes with many large polygons (σ = 3, β = +1) the cells they cover become negatives and pull the AUC down (−0.0505): the pre-specified secondary prediction that `rep_point` stays within 0.05 of the object AUC failed in 1 of 61 scenarios, so `rep_point` is not free of bias. Second, when all events share the same β, pooling events and taking event medians give nearly the same cell-level AUC: in all 24 multi-event scenarios the median of V1 − V2 over replicates lay within ±0.012, although in scenarios with skewed event sizes, event effects and β ≤ 0, 15–20 % of replicates still differed by 0.1 or more. The Changwon contrast between V1 (0.436) and V2 (0.791) is not reproduced by that generator. In Changwon, only the event that carries 98.8 % of the weight has a strong negative coupling (β̂ = −0.83 for the September 2024 event, |β̂| ≤ 0.17 for development events).

In the post hoc anchor, the formula value Δ̂* and the observed `f10` gap agreed in rank across 50 event–score pairs (Spearman 0.885). For L1 on the pooled holdout σ̂ = 2.46 and β̂ = −0.80 give Δ̂* = −0.406 against an observed −0.276. The Changwon holdout sits in the σ ≈ 2.5 region of the synthetic space (top-10 % weight share 0.73, synthetic 0.74), and its covariance factors (ρ = −0.48, sd = 0.20, concentration factor 2.01) multiply to the observed size-weighting term (−0.198). The formula fits less well where polygon loss dominates (impervious fraction: −0.434 predicted vs. −0.194 observed) or where the relation to log-area is not linear (relative elevation: −0.085 vs. −0.154).

### 4.4 Learned terrain models are not distinguishable from slope alone

Over the seven test events with a learned score and at least five positive cells, the median cell-level AUC was 0.872 for slope alone and 0.855 for the walk-forward RF-F1 (Table 7). By the pre-specified rule, the claim that learned terrain models add skill over trivial baselines was dropped. The two summaries point in different directions: the median of per-event differences (RF − slope) is +0.030 and RF was higher in four of the seven events. Slope, both HAND variants and TWI passed the gate in all eight evaluable events; L1 met the AUC condition in five of eight and the capture condition in four of eight.

**Table 7.** Cell-level AUC per test event (reference rule, all cells).

| Test event | Role | Positive cells | Slope alone | RF-F1 (walk-forward) | RF − slope |
|---|---|---:|---:|---:|---:|
| 2012 | development | 206 | 0.872 | 0.780 | −0.091 |
| 2014 | development | 132 | 0.813 | 0.852 | +0.039 |
| 2016 | development | 170 | 0.871 | 0.901 | +0.030 |
| 2019 | development | 56 | 0.913 | 0.972 | +0.059 |
| 2025-07 | development | 25 | 0.952 | 0.855 | −0.098 |
| 2023-08-10 | holdout | 18 | 0.831 | 0.892 | +0.061 |
| 2024-09-20 | holdout | 1254 | 0.923 | 0.843 | −0.080 |
| Median | | | 0.872 | 0.855 | +0.030 |

*Source: run `m1_20260926T160821Z_a181f6c`, `decision.json`, `metrics_long.csv`. Differences are computed from unrounded AUCs. Post hoc design.*

At the event level the evidence is weak in both directions. The random-effects pooled logit difference RF − slope was −0.141 [−0.907, +0.625] over the same seven events; all seven leave-one-event-out variants and all estimator variants gave the same classification (interval covering zero). For polygon-level AUC the difference was −0.131 [−1.081, +0.819] on development events and +0.186 [−0.096, +0.468] on holdout events; we therefore do not claim that RF ranks polygons better than slope. Among all pairwise contrasts, only RF against relative elevation excluded zero.

Pooled over the six development events, cell-level AUC was 0.897 [0.826, 0.941] for slope, 0.884 [0.843, 0.916] for HAND (OSM), 0.876 [0.746, 0.944] for RF-F1 and 0.762 [0.392, 0.940] for L1, with high heterogeneity (I² = 0.74–0.99). Only the two HAND variants had 95 % prediction intervals entirely above 0.70 (HAND-OSM [0.764, 0.947]); the interval for slope started at 0.645 and for RF at 0.507. The holdout contributes k = 2 events to cell-level AUC, and pooled intervals are nearly uninformative (slope [0.026, 1.000], RF [0.326, 0.987]). How holdout events are summarised also changes the number: for L1 the cell-weighted mean is 0.438, the equal-event mean 0.648 and the random-effects mean 0.632.

Within harder backgrounds, no score reached a median cell-level AUC of 0.70 among flat cells (best: slope 0.693); among urban cells only the two HAND variants (0.722, 0.746) and slope (0.700) did (Appendix E, Table E1). Much of the apparent terrain skill is separation of steep uplands from lowland. In the September 2024 event, 1112 of 1254 positive cells fall in the agricultural proxy stratum.

Nesting the RF configuration choice inside earlier events lowered the median cell-level AUC over six events from 0.873 (fixed configuration) to 0.865, a difference of 0.008, within the pre-specified 0.02, so the fixed configuration was not judged optimistic. Two secondary results point the other way: selecting across four model families lowered the median to 0.841 (−0.032), and the median top-20 % capture fell from 0.902 to 0.761. Nested selection chose the feature set without the city flood-map depth in all four prior-event sets. The slope-alone median over the same six events (0.892) still exceeded both.

### 4.5 The rainfall-climatology axis ranks inversely

The exposure axis of L1 alone scored a cell-level AUC of 0.389 [0.267, 0.528] on the development events and 0.147 [0.086, 0.341] on the pooled holdout, below 0.5 in both. The sensitivity axis alone scored 0.869 and 0.735. Adding the exposure axis therefore lowered L1 in both periods. We report this as an observation only. Our inputs cannot separate explanations such as the gauge climatology measuring orographic rainfall over uplands while floods occur in lowlands, or rainfall climatology being the wrong scale for event-driven flooding. Damage-causing floods have been characterised by event-scale rainfall properties (Spekkers et al., 2013; Bernet et al., 2019); event rainfall (e.g. radar) would be needed to test these explanations here.

### 4.6 Reproducibility check

A clean-commit rerun of the official holdout scoring (run `holdout_20260926T164805Z_7f7968f_84ef30a7`) produced the same gate hash and identical gate values for all ten scores (e.g. L1 0.4357 / 0.6025 / 0.0734). Under the pre-specified comparison rule the rerun was nevertheless classed as inconsistent. 1966 of 5670 metric rows at the area and polygon levels differed by at most 1.8 × 10⁻¹², and the recorded union area differed by 2.0 × 10⁻¹³ km². The polygons whose areas changed were all reprojected from EPSG:5186/5187; none of the 125 ministry polygons stored in EPSG:5179 changed. We therefore attribute the differences to last-digit differences in coordinate transformation; this could not be confirmed because the earlier run did not record the PROJ version. We keep the earlier run as the cited source and report the rerun alongside.

## 5 Discussion

### 5.1 What the gate failure does and does not show

The failure of L1 is robust in one specific sense: no labelling setting among the 32 we tried brings the pooled-holdout margin to the gate, and capture never exceeded 0.412. It is not a statement about many independent events. The pooled verdict is almost entirely the verdict on the September 2024 event, the event-median gate passes at the reference setting, and the holdout provides only two events with positive cells. The failure is also not uniform across flood types: for urban polygons L1's polygon-level AUC was 0.910, while for agricultural polygons it was 0.608. One hypothesis consistent with these numbers is a mismatch of purpose: L1 is built from indicators of urban pluvial flooding, whereas the weight of the holdout inventory lies in agricultural inundations, mostly in polygons larger than 20 000 m², that may be driven by other processes. This hypothesis is not tested here. The city's pluvial flood map, which targets urban drainage failure, also failed on the pooled holdout (0.450), which fits the same explanation but does not establish it.

The evaluation is of a pre-frozen index on events whose traces were obtained after freezing; the events themselves predate the index. Stronger confirmation would require traces sealed before scoring, for example events after 2026 or other cities scored with a fixed protocol. We drafted a multi-city protocol but did not register or execute it (Sect. 5.4).

### 5.2 Cell-level AUC is a choice of weights

Equation (1) turns a technical choice into an explicit weighting of the inventory. Under threshold rules, a polygon's vote is the number of cells it fills; under `soft` it is its area; under `rep_point` it is one cell. Equation (2) separates two things that are often confounded when cell-level and polygon-level scores disagree: which polygons are counted (loss) and how much each counts (size weighting). Eq. (3) says when the weighting matters: only when weights are concentrated and contributions both vary and correlate with weight. Eq. (4) gives an order of magnitude for log-normal inventories. The synthetic results show the mechanism does not depend on Changwon. A gap of 0.1 or more needs both a broad size distribution and a size-dependent detectability. Neither alone is enough, and when β = 0 small effective samples produce only chance gaps.

This connects the inventory literature on mapping and sampling choices (Hussin et al., 2016; Steger et al., 2016, 2017; Ozturk et al., 2021) and on validation design (Landwehr et al., 2024) with a quantity that can be computed and reported for any cell-level AUC. We suggest that evaluations of flood susceptibility or vulnerability maps against polygon inventories report:

1. both cell-level and polygon-level scores;
2. the weight shares of events, land-use classes and size classes and the effective number of polygons n_eff;
3. the three terms of Eq. (2);
4. the event as the sampling unit, with event-level intervals rather than cell counts.

No single label rule removes the problem. `rep_point` removed size weighting in our data but was not free of bias in synthetic landscapes with large polygons, and `soft` maximised size weighting.

### 5.3 Trivial baselines and the claim we withdrew

Before these checks, our working claim was that terrain-based learned models identify flood locations well. Slope alone matched them on median cell-level AUC. The event-level synthesis could not distinguish RF from slope, HAND or TWI, and nesting configuration selection did not change the picture. Within flat or urban cells all scores were weak. We therefore report learned models as comparators, not as a validated alternative to L1. Their holdout gate values (e.g. RF-F1 trained on events up to 2019: 0.843 / 0.763) come from a post hoc design and a single dominant event. Temporal and event-wise evaluations elsewhere report AUCs of roughly 0.73–0.88 (Lee et al., 2017; Mobley et al., 2021), and random splits often report 0.87 or more (Seleem et al., 2022; Asrade et al., 2026). Our terrain numbers fall in the temporal range. The comparison is only indicative because inventories, grids and labels differ. Two recent Korean studies are closest in data: a machine-learning susceptibility study for Seoul that examined sampling variability (Lee et al., 2026) and a transferability study between regions and events using official flood traces (Han and Lee, 2026, preprint). Neither audits a frozen guideline index.

### 5.4 Limitations

- **Single city.** A multi-city replication was planned and a protocol drafted, but it was not registered or run; we make no replication claim. The synthetic demonstration supports the generality of the mechanism, not of the Changwon numbers. Transfer of data-driven urban flood models between areas is known to be difficult (Seleem et al., 2023; Cache et al., 2024).
- **Few events.** The holdout has two events with positive cells under the reference rule, one of which dominates. Development pooling rests on six events with high heterogeneity. Standard errors are back-calculated from percentile intervals and are unstable for events with only three clusters. Paired differences were pooled assuming zero correlation between the two scores' resampling errors; the protocol expected this to be conservative, but in one of five development events (2025) the correlation was negative and the assumption understated the standard error.
- **Post hoc designs.** All analyses beyond the L1 gate were designed after the L1 result was known, and the learned models' feature candidates were chosen after a holdout diagnostic whose time was not recorded.
- **Presence-only labels.** Unrecorded floods make the background impure. Small urban floods are under-recorded, and the development inventory has no land-use attribute, so its composition by land use is unknown.
- **Applicability.** We did not map where the learned models extrapolate beyond their training conditions (Meyer and Pebesma, 2021, 2022).
- **Inputs.** The 90 m DEM limits micro-topography, especially within flat and urban strata; urban inundation modelling is known to be sensitive to grid scale (Fewtrell et al., 2008). Inputs describe 2024–2025 conditions, and the rainfall-climatology period overlaps the holdout years. Pumping stations may be sited where floods occurred before (reverse causation).
- **Reproducibility.** The official rerun matched on gate values but not under the strict pre-specified rule. The first official scoring and the cited run were made from uncommitted code (flagged `-dirty`).

## 6 Conclusions

A guideline-structured urban flood index, frozen before the release of flood traces for four later-scored events, failed its pre-specified gate in Changwon, and the failure held under 32 combinations of label rule and grid size. The same traces scored at the polygon level give a much higher AUC. The difference is exactly accounted for by treating cell-level AUC as a weighted mean of polygon contributions: one event, agricultural polygons and polygons larger than 20 000 m² carry almost all of the weight, and most small urban polygons are lost. Synthetic inventories show that such gaps arise whenever polygon sizes are dispersed and detectability depends on size, with a closed-form approximation for their magnitude. Trivial terrain baselines matched learned models, which led us to drop a claim of added skill. For index audits with administrative flood traces we recommend reporting cell- and polygon-level scores together, treating events as the sampling unit, and publishing the weight concentration behind every cell-level AUC.

---

## Code and data availability

Code, protocols, run records and derived outputs are in the project repository [repository URL to be inserted; branch `cloud-base`, commit to be fixed at submission]. Each result is tied to a run ID (Sect. 3.8; `docs/paper/numbers_provenance.md`). A Zenodo deposit is planned. A candidate list of 458 files has been prepared (340 open, 5 restricted, 111 hash-only, 2 excluded; `docs/q1/M6_zenodo.md`), but no licence file exists yet and the redistribution terms of the city and ministry flood traces have not been confirmed. Until then the raw traces will be described with access procedures and file hashes rather than redistributed, in line with the FAIR principles (Wilkinson et al., 2016). [DOI to be inserted after deposit.]

## Author contributions

[To be completed by the authors.]

## Competing interests

[To be completed by the authors.]

## Use of AI tools

Analysis code, run orchestration, cross-checks and this draft were produced with AI coding agents (Claude, Codex) working under a repository harness that fixes protocols before computation and requires independent recomputation by a different model. [Authors to state their responsibility for the content and describe the tools as required by the journal.]

## Acknowledgements and financial support

[To be completed.]

---

## References

See `docs/paper/references.md` for the verified list with DOIs and metadata sources. Author–year citations in the text correspond one-to-one to that list. Items marked `[미확인]` in the text are not in the list and must be checked before submission.

---

## Appendix A: Derivations

**A1 Identity (1).** With F the mid-rank distribution of negative mass, A = Σ_i p_i F(s_i) / Σ_i p_i. Since Σ_k π_ki = 1 for every positive cell, Σ_k W_k A_k = Σ_k Σ_i p_i π_ki F(s_i) = Σ_i p_i F(s_i) and Σ_k W_k = Σ_i p_i, so A = Σ_k w_k A_k. Cells with missing scores are excluded from both sides.

**A2 Covariance form (3).** Let w̃_k = W_k / Σ_S W on the surviving set S with n_S members and Ā = mean_S A_k. If all positive mass belongs to S, A = Σ_S w̃_k A_k and A − Ā = Σ_S (w̃_k − 1/n_S)(A_k − Ā) = n_S Cov_S(w̃, A). With population moments, n_S sd(w̃) = √(n_S Σ w̃² − 1) = √(n_S/n_eff,S − 1), giving Eq. (3).

**A3 Tilt formula (4).** With ζ ~ N(0, 1) and weights ∝ e^{σζ}, the weighted distribution of ζ is N(σ, 1). For a cell score z + μ against an independent background z′ ~ N(0, 1), P(z + μ > z′) = Φ(μ/√2), and E[Φ((m + cZ)/√2)] = Φ(m/√(2 + c²)). With μ_k = μ0 + βζ_k + τε_k this gives Φ(μ0/D) for the unweighted and Φ((μ0 + βσ)/D) for the area-weighted mean, D = √(2 + β² + τ²).

## Appendix B: Composite index CDRI (discussion only)

L1 was designed as the hazard component H of a composite response-priority index CDRI = H^w E^w V^w D^w (exposure: population and housing counts; vulnerability: share of residents aged 65 or over; D: one minus access to shelters and emergency facilities; w = 1/4). The components were rescaled to [0.05, 1] and priority cells were selected by non-maximum suppression within 300 m. Validation of such a composite against flood occurrence mixes a hazard outcome with a risk construct; validation against outcomes that match the construct, such as damage or deaths, is the recommended route (Molinari et al., 2019; Rufat et al., 2019; Bakkensen et al., 2017; Tellman et al., 2020; Moreira et al., 2021). We report only what the traces can say, as a post hoc check.

Within the 10 202 populated cells, the holdout traces leave 102 positive cells. The cell-level AUC of CDRI was 0.340 with H = L1, 0.392 with H = sensitivity axis, 0.480 with H = RF-F1 trained on events up to 2019, and 0.496 with the frozen RF-F1. The corresponding development values were 0.539 (L1) and 0.732 (RF-F1 up to 2019). The top-20 priority cells chosen with H = L1 and H = RF-F1 (up to 2019) shared 5 of 20 cells. We do not interpret these values as a test of prioritisation, which would require outcomes such as damage or emergency-call records that we do not have. *Source: run `posthoc_h_20260926T134611Z_3d14fc1`, `summary.json`.*

## Appendix C: Forecast-conditioned extension (discussion only)

We also tested, under a separate protocol fixed before evaluation, whether day-ahead precipitation forecasts add information on whether a recorded flood event occurs and where, following work on rainfall thresholds and event-conditional location models for urban pluvial flooding (Tian et al., 2019; Li and Willems, 2020). The catalogue held 84 storms, of which 72 were labelled (10 flood events). A logistic model on the day-ahead forecast gave a leave-one-event-out Brier skill score of 0.055 [−0.249, 0.210] and an AUC of 0.723 on 44 storms with 5 flood events. The first pre-specified criterion (the lower end of this interval above zero) was not met. On the frozen holdout (18 storms, 4 flood events) the Brier skill score was 0.219 [−0.179, 0.468]. Heavy-rain warnings detected every recorded flood event, with false-alarm ratios of 0.50–0.58. The combined occurrence × location probability did not improve a cell-level Brier score over climatology (BSS 0.0002 [−0.0038, 0.0017]); the second criterion was not met either. Within events, location rankings were stable (cell-level AUC 0.84–0.97 where positive cells exist), which is the same terrain signal discussed in Sect. 4.4. We do not claim that forecasts improve flood prediction. *Source: `docs/FORECAST_RESULTS.md` (runs `trigger_20260926T125638548044Z_684161e`, `combined_20260926T125729Z_684161e`).*

## Appendix D: Chronology (summary)

| Step | Time (KST) | Record |
|---|---|---|
| Gate recorded in the methods specification | ≤ 2026-08-19 14:12 | commit `e706cb6` |
| Gate constants in code; first L1 computation | 2026-09-07 23:34–23:38 | ledger; commit `a1c2743` |
| Last change of the L1 formula | ≤ 2026-09-08 00:50 | commit `85fc544` |
| Development gate passed (AUC 0.750, capture 0.544) | ≤ 2026-09-16 17:15 | commit `dfab756` |
| Holdout traces received | 2026-09-24 (date) | `data/raw/README.md` |
| Holdout first read (unit tests, no scoring) | ≤ 2026-09-24 18:18:20 | RF v1 prespec record |
| Feature-set diagnostic on the holdout | not recorded (between the two rows above and below) | — |
| First official holdout scoring (L1 fails) | 2026-09-24 18:38:54 | run `holdout_20260924T093854Z_ae9c122_85559f26` |
| RF re-selection after leakage fix | 2026-09-24 18:49:16 | RF v2 prespec record |
| Cited holdout run | 2026-09-24 19:09:39 | run `holdout_20260924T100939Z_ae9c122-dirty_cf388a23` |
| Clean-commit rerun | 2026-09-27 01:48:05 | run `holdout_20260926T164805Z_7f7968f_84ef30a7` |

*Source: `docs/q1/M6_chronology.md` (run `m6_20260926T164903Z_7f7968f`, 42 entries, all verified). Commit times are upper bounds.*

## Appendix E: Supplementary tables

**Table E1.** Median cell-level AUC by background stratum (development and holdout events with ≥ 5 positive cells in the stratum; number of events: flat 8, RF 7; urban 6; agricultural proxy 5; populated 7).

| Score | All | Flat (slope ≤ 5°) | Urban (imperv. ≥ 0.5) | Agricultural proxy | Populated |
|---|---:|---:|---:|---:|---:|
| Slope alone | 0.885 | 0.693 | 0.700 | 0.686 | 0.778 |
| HAND (OSM) | 0.870 | 0.672 | 0.722 | 0.750 | 0.788 |
| HAND (flow accumulation) | 0.883 | 0.669 | 0.746 | 0.742 | 0.817 |
| TWI | 0.857 | 0.640 | 0.637 | 0.636 | 0.721 |
| Impervious fraction | 0.708 | 0.551 | 0.567 | 0.499 | 0.704 |
| Relative elevation | 0.537 | 0.517 | 0.424 | 0.483 | 0.356 |
| RF-F1 (walk-forward) | 0.855 | 0.654 | 0.626 | 0.664 | 0.752 |
| Logistic F1 (walk-forward) | 0.846 | 0.562 | 0.532 | 0.659 | 0.669 |
| L1 (frozen) | 0.788 | 0.622 | 0.632 | 0.299 | 0.741 |
| Sensitivity axis | 0.856 | 0.656 | 0.689 | 0.632 | 0.689 |

*Source: run `m1_20260926T160821Z_a181f6c`, `median_table.csv`. The "All" column includes 2006 for scores without a learned component, hence 0.885 for slope against 0.872 in Table 7.*

**Table E2.** Random-effects pooled cell-level AUC over the six development events (REML, modified HKSJ interval, back-transformed from logit).

| Score | k | Pooled AUC [95 % CI] | 95 % prediction interval | I² |
|---|---:|---|---|---:|
| Slope alone | 6 | 0.897 [0.826, 0.941] | [0.645, 0.977] | 0.89 |
| HAND (OSM) | 6 | 0.884 [0.843, 0.916] | [0.764, 0.947] | 0.74 |
| HAND (flow accumulation) | 6 | 0.895 [0.853, 0.926] | [0.758, 0.958] | 0.82 |
| TWI | 6 | 0.855 [0.791, 0.902] | [0.663, 0.947] | 0.86 |
| RF-F1 (walk-forward) | 5 | 0.876 [0.746, 0.944] | [0.507, 0.980] | 0.82 |
| Logistic F1 (walk-forward) | 5 | 0.846 [0.588, 0.955] | [0.188, 0.992] | 0.76 |
| L1 (frozen) | 6 | 0.762 [0.392, 0.940] | [0.036, 0.996] | 0.97 |
| Sensitivity axis | 6 | 0.877 [0.711, 0.954] | [0.285, 0.992] | 0.95 |

*Source: run `m2_20260926T165115Z_1ffdde7`, `pooled.csv`. Post hoc summary. Figure 5 shows the forest plot.*

---

## Figures (plan)

| Figure | Content | Status and data source |
|---|---|---|
| 1 | Study area: 100 m grid, development and holdout traces coloured by event, land-use class of holdout polygons | To be drawn (lead analyst only; reads holdout geometry) from `data/processed/layers/layer1_flood.gpkg` and the trace registry |
| 2 | Schematic of the eight label rules on one cell and the weight W_k of a small and a large polygon | To be drawn (schematic, no data) |
| 3 | Decomposition bars for L1 pooled holdout by rule (size weighting, within, loss) and weight shares by event, land use and area class | To be drawn from `artifacts/q1/M4/m4_20260926T170511Z_1edf87c/decomposition.csv`, `object_contrib.parquet` |
| 4 | Synthetic σ × β map of median gap and P(|gap| ≥ 0.1) with Δ* contours | Existing: `artifacts/q1/M4S/m4s_20260926T175809Z_3e8bc1c/gap_map_redrawn.png` |
| 5 | Forest plot of event-level cell AUC and pooled estimates | Existing: `artifacts/q1/M2/m2_20260926T165115Z_1ffdde7/forest_grid_auc.png` |
| 6 | Polygon survival by area class and grid size (holdout and development) | To be drawn from `artifacts/q1/M4/m4_20260926T170511Z_1edf87c/survival_summary.csv` |
