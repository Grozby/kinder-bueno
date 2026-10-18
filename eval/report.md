# Evaluation report

## Queries

| use case | query | results | expected found | recall@10 | judged relevant | expansion terms |
|---|---|---|---|---|---|---|
| glucose | continuous glucose monitoring | 10 | Diabetes Center Berne | 20% | 6/10 | 8 |
| glucose | glucose sensors | 10 | Diabetes Center Berne | 20% | 4/10 | 15 |
| glucose | biosensing for diabetes | 10 | Diabetes Center Berne, Lilian Witthauer | 40% | 5/10 | 11 |
| surgery | computer-assisted surgery | 10 | – | 0% | 1/10 | 10 |
| surgery | surgical robots | 10 | – | 0% | 3/10 | 12 |
| surgery | image-guided intervention | 10 | – | 0% | 6/9 | 12 |
| cardio | cardiovascular engineering | 10 | Dominik Obrist | 25% | 7/9 | 15 |
| cardio | heart valve research | 10 | Longnus Lab | 25% | 4/10 | 16 |
| cardio | implant materials | 10 | – | 0% | 5/10 | 16 |

## Metrics (plan 10.2)

| metric | value | target |
|---|---|---|
| recall@10 (mean of 9 queries) | 14% | ≥ 80% |
| lay-term recall@10 (phrasings b, c) | 14% | ≥ 80% |
| phrasing overlap, glucose (mean Jaccard of top-10 sets) | 53% | report |
| phrasing overlap, surgery (mean Jaccard of top-10 sets) | 29% | report |
| phrasing overlap, cardio (mean Jaccard of top-10 sets) | 18% | report |
| traceability (displayed claims shown + source URL) | 100% | 100% |
| field fill, person results: role | 100% | report |
| field fill, person results: affiliations | 79% | report |
| field fill, person results: expertise | 0% | report |
| field fill, person results: sources | 100% | report |
| judged precision@10 [PoC] (mean of 9 judged queries) | 47% | report |
| judge gold agreement [PoC] (gold hits judged relevant) | 100% (6 / 6) | report; < 80% = judge not reliable |
| extraction drop rate (unverified raw claims) | 13% (221 / 1705) | report |

## Source coverage

| source | pages | entities | shown claims |
|---|---|---|---|
| artorg | 45 | 273 | 929 |
| dcb | 30 | 127 | 396 |
| unibe | 25 | 83 | 242 |

## Judge verdicts [PoC] (verified claims)

| verdict | claims |
|---|---|
| not judged | 1567 |

## Feedback [PoC]

| rating | count |
|---|---|
| – | 0 |

The eval judge [PoC] is the same model family as the extractor, so it is biased (plan 3): a precision signal, not ground truth. Verdicts and reasons: `eval/judge_log.jsonl`.
