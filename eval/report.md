# Evaluation report

## Queries

| use case | query | results | expected found | recall@10 | judged relevant | expansion terms |
|---|---|---|---|---|---|---|
| glucose | continuous glucose monitoring | 10 | Lilian Witthauer, Stavroula Mougiakakou, AI in Health and Nutrition | 50% | 5/10 | 8 |
| glucose | glucose sensors | 10 | Diabetes Center Berne, Lilian Witthauer, Stavroula Mougiakakou, AI in Health and Nutrition | 67% | 6/10 | 15 |
| glucose | biosensing for diabetes | 10 | Diabetes Center Berne, Lilian Witthauer, Thomas Züger, Stavroula Mougiakakou, AI in Health and Nutrition | 83% | 9/10 | 11 |
| surgery | computer-assisted surgery | 10 | Chair for Image-guided Therapy, Neuro Robotics Group, Artificial Intelligence in Medical Imaging | 43% | 9/10 | 10 |
| surgery | surgical robots | 10 | Chair for Image-guided Therapy, Neuro Robotics Group, Manuela Eugster | 43% | 8/10 | 12 |
| surgery | image-guided intervention | 10 | Chair for Image-guided Therapy, Artificial Intelligence in Medical Imaging | 29% | 9/10 | 12 |
| cardio | cardiovascular engineering | 10 | Dominik Obrist, Cardiovascular Engineering, Cardiovascular Research Cluster Bern, Odening Lab | 80% | 8/10 | 15 |
| cardio | heart valve research | 10 | Dominik Obrist, Cardiovascular Engineering, Cardiovascular Research Cluster Bern, Odening Lab, Longnus Lab | 100% | 8/10 | 16 |
| cardio | heart valve prostheses | 10 | Dominik Obrist, Cardiovascular Engineering, Odening Lab, Longnus Lab | 80% | 5/10 | 13 |

## Metrics (plan 10.2)

| metric | value | target |
|---|---|---|
| recall@10 (mean of 9 queries) | 64% | ≥ 80% |
| lay-term recall@10 (phrasings b, c) | 67% | ≥ 80% |
| phrasing overlap, glucose (mean Jaccard of top-10 sets) | 60% | report |
| phrasing overlap, surgery (mean Jaccard of top-10 sets) | 41% | report |
| phrasing overlap, cardio (mean Jaccard of top-10 sets) | 48% | report |
| traceability (displayed claims shown + source URL) | 100% | 100% |
| field fill, person results: role | 100% | report |
| field fill, person results: affiliations | 100% | report |
| field fill, person results: expertise | 0% | report |
| field fill, person results: unit_topics | 98% | report |
| field fill, person results: sources | 100% | report |
| judged precision@10 [PoC] (mean of 9 judged queries) | 74% | report |
| judge gold agreement [PoC] (gold hits judged relevant) | 76% (25 / 33) | judge not reliable |
| extraction drop rate (unverified raw claims) | 13% (221 / 1705) | report |

## Source coverage

| source | pages | entities | shown claims |
|---|---|---|---|
| artorg | 45 | 268 | 907 |
| dcb | 30 | 125 | 396 |
| unibe | 25 | 83 | 232 |

## Claim judge verdicts [PoC] (verified expertise, description, bio, unit_type claims; plan 7.8)

| verdict | claims |
|---|---|
| partial | 123 |
| supported | 403 |
| unsupported | 32 |

## Feedback [PoC]

| rating | count |
|---|---|
| – | 0 |

The eval judge [PoC] is the same model family as the extractor, so it is biased (plan 3): a precision signal, not ground truth. Verdicts and reasons: `eval/judge_log.jsonl`.
