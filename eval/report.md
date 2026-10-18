# Evaluation report

## Queries

| use case | query | results | expected found | recall@10 | judged relevant | expansion terms |
|---|---|---|---|---|---|---|
| glucose | continuous glucose monitoring | 10 | Diabetes Center Berne, Lilian Witthauer | 40% | 6/10 | 8 |
| glucose | glucose sensors | 10 | Diabetes Center Berne, Lilian Witthauer | 40% | 10/10 | 15 |
| glucose | biosensing for diabetes | 10 | Lilian Witthauer, Thomas Züger, Christoph Stettler | 60% | 9/10 | 11 |
| surgery | computer-assisted surgery | 10 | Chair for Image-guided Therapy | 17% | 6/10 | 10 |
| surgery | surgical robots | 10 | Chair for Image-guided Therapy, Neuro Robotics Group, Manuela Eugster | 50% | 5/10 | 12 |
| surgery | image-guided intervention | 10 | Chair for Image-guided Therapy, Manuela Eugster | 33% | 2/10 | 12 |
| cardio | cardiovascular engineering | 10 | Dominik Obrist, Cardiovascular Research Cluster Bern, Odening Lab | 75% | 6/9 | 15 |
| cardio | heart valve research | 10 | Dominik Obrist, Cardiovascular Research Cluster Bern, Odening Lab, Longnus Lab | 100% | 10/10 | 16 |
| cardio | implant materials | 10 | – | 0% | 2/9 | 16 |

## Metrics (plan 10.2)

| metric | value | target |
|---|---|---|
| recall@10 (mean of 9 queries) | 46% | ≥ 80% |
| lay-term recall@10 (phrasings b, c) | 47% | ≥ 80% |
| phrasing overlap, glucose (mean Jaccard of top-10 sets) | 56% | report |
| phrasing overlap, surgery (mean Jaccard of top-10 sets) | 34% | report |
| phrasing overlap, cardio (mean Jaccard of top-10 sets) | 17% | report |
| traceability (displayed claims shown + source URL) | 100% | 100% |
| field fill, person results: role | 98% | report |
| field fill, person results: affiliations | 100% | report |
| field fill, person results: expertise | 0% | report |
| field fill, person results: unit_topics | 80% | report |
| field fill, person results: sources | 100% | report |
| judged precision@10 [PoC] (mean of 9 judged queries) | 63% | report |
| judge gold agreement [PoC] (gold hits judged relevant) | 85% (17 / 20) | report; < 80% = judge not reliable |
| extraction drop rate (unverified raw claims) | 13% (221 / 1705) | report |

## Source coverage

| source | pages | entities | shown claims |
|---|---|---|---|
| artorg | 45 | 268 | 904 |
| dcb | 30 | 126 | 396 |
| unibe | 25 | 83 | 231 |

## Claim judge verdicts [PoC] (verified expertise, description, bio, unit_type claims; plan 7.8)

| verdict | claims |
|---|---|
| not judged | 3 |
| partial | 120 |
| supported | 399 |
| unsupported | 36 |

## Feedback [PoC]

| rating | count |
|---|---|
| – | 0 |

The eval judge [PoC] is the same model family as the extractor, so it is biased (plan 3): a precision signal, not ground truth. Verdicts and reasons: `eval/judge_log.jsonl`.
