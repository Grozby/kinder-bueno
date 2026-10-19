# Evaluation report

## Queries

| use case | query | results | expected found | recall@10 | judged relevant | expansion terms |
|---|---|---|---|---|---|---|
| glucose | continuous glucose monitoring | 10 | Diabetes Center Berne, Thomas Züger, AI in Health and Nutrition | 43% | 8/10 | 8 |
| glucose | glucose sensors | 10 | Diabetes Center Berne, Lilian Witthauer, AI in Health and Nutrition | 43% | 9/10 | 15 |
| glucose | biosensing for diabetes | 10 | Diabetes Center Berne, Lilian Witthauer, Thomas Züger, AI in Health and Nutrition | 57% | 10/10 | 11 |
| surgery | computer-assisted surgery | 10 | Chair for Image-guided Therapy, Neuro Robotics Group, Artificial Intelligence in Medical Imaging, Raphael Sznitman | 57% | 9/10 | 10 |
| surgery | surgical robots | 10 | Chair for Image-guided Therapy, Neuro Robotics Group, Manuela Eugster, Artificial Intelligence in Medical Imaging | 57% | 9/10 | 12 |
| surgery | image-guided intervention | 10 | Chair for Image-guided Therapy, Neuro Robotics Group, Artificial Intelligence in Medical Imaging, Raphael Sznitman | 57% | 9/10 | 12 |
| cardio | cardiovascular engineering | 10 | Dominik Obrist, Cardiovascular Engineering, Odening Lab, Longnus Lab | 80% | 10/10 | 15 |
| cardio | heart valve research | 10 | Dominik Obrist, Cardiovascular Engineering, Odening Lab, Longnus Lab | 80% | 7/10 | 16 |
| cardio | heart valve prostheses | 10 | Dominik Obrist, Cardiovascular Engineering, Odening Lab, Longnus Lab | 80% | 4/10 | 13 |
| rehab | neurorehabilitation | 10 | Gerontechnology and Rehabilitation, Kenneth Hunt | 33% | 10/10 | 13 |
| rehab | recovery after a stroke | 10 | Gerontechnology and Rehabilitation, Kenneth Hunt, Aleksandra Eberhard-Moscicka, Bassetti Lab | 67% | 9/10 | 14 |
| rehab | motor rehabilitation | 10 | Gerontechnology and Rehabilitation, Tobias Nef, Kenneth Hunt | 50% | 10/10 | 13 |
| immuno | cancer immunotherapy | 10 | Ochsenbein Lab, Bill Lab, Karkampouna Lab, Bernasconi Lab | 57% | 9/10 | 13 |
| immuno | immune treatment for cancer | 10 | Ochsenbein Lab, Bill Lab, Karkampouna Lab, Bernasconi Lab | 57% | 10/10 | 16 |
| immuno | tumor immunology | 10 | Ochsenbein Lab, Bill Lab, Karkampouna Lab, Bernasconi Lab | 57% | 10/10 | 12 |
| microbiome | gut microbiome | 10 | Balmer Lab, Maria Luisa Balmer, Ganal-Vonarburg Lab, Frei Lab, Zysset Lab | 71% | 7/10 | 12 |
| microbiome | gut bacteria | 10 | Balmer Lab, Maria Luisa Balmer, Frei Lab, Zysset Lab | 57% | 7/10 | 12 |
| microbiome | intestinal microbiota | 10 | Balmer Lab, Ganal-Vonarburg Lab, Al Nabhani Lab, Frei Lab, Zysset Lab | 71% | 8/10 | 12 |

## Metrics (plan 10.2)

| metric | value | target |
|---|---|---|
| recall@10 (mean of 18 queries) | 60% | ≥ 80% |
| lay-term recall@10 (phrasings b, c) | 61% | ≥ 80% |
| phrasing overlap, glucose (mean Jaccard of top-10 sets) | 62% | report |
| phrasing overlap, surgery (mean Jaccard of top-10 sets) | 43% | report |
| phrasing overlap, cardio (mean Jaccard of top-10 sets) | 54% | report |
| phrasing overlap, rehab (mean Jaccard of top-10 sets) | 56% | report |
| phrasing overlap, immuno (mean Jaccard of top-10 sets) | 37% | report |
| phrasing overlap, microbiome (mean Jaccard of top-10 sets) | 58% | report |
| traceability (displayed claims shown + source URL) | 100% | 100% |
| field fill, person results: role | 100% | report |
| field fill, person results: affiliations | 100% | report |
| field fill, person results: expertise | 38% | report |
| field fill, person results: unit_topics | 96% | report |
| field fill, person results: sources | 100% | report |
| judged precision@10 [PoC] (mean of 18 judged queries) | 86% | report |
| judge gold agreement [PoC] (gold hits judged relevant) | 91% (63 / 69) | report; < 80% = judge not reliable |
| extraction drop rate (unverified raw claims) | 16% (820 / 5263) | report |

## Source coverage

| source | pages | entities | shown claims |
|---|---|---|---|
| artorg | 110 | 362 | 1457 |
| dcb | 30 | 132 | 439 |
| unibe | 200 | 805 | 3181 |

## Claim judge verdicts [PoC] (verified expertise, description, bio, unit_type claims; plan 7.8)

| verdict | claims |
|---|---|
| not judged | 1 |
| partial | 378 |
| supported | 1268 |
| unsupported | 60 |

## Feedback [PoC]

| rating | count |
|---|---|
| – | 0 |

The eval judge [PoC] is the same model family as the extractor, so it is biased (plan 3): a precision signal, not ground truth. Verdicts and reasons: `eval/judge_log.jsonl`.
