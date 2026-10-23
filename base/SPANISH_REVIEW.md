# Spanish template review

This historical review describes the Spanish template changes integrated into the M3 snapshot. The M2 review baseline had SHA256 `221e2e7856e92f2c2f63f873c9fbc2a6f9017df19af48e73956808c24cedc18f`. It is retained as `touchline_core.before.py` so the included Spanish regression can compare every fixture snapshot and English card with that baseline. That digest is not the current application source hash. Later source changes require their own validation. The October 22 revised candidate separates brief fan copy from analyst detail. Fan cards and recap keep the score, observable counts and exact ratios while leaving internal event IDs and historical-receipt terminology to the producer/analyst layer. Analyst text retains event-window and causal/proxy qualifications. The underlying fact/evidence payload is shared across audiences. Spanish templates follow the same split, and the English companion remains available. These changes require fresh checks for numbers, evidence IDs, bounded meaning and companion text; they do not inherit the historical language result below. Native-speaker human review remains unverified.

Confidence is high for the listed spelling, grammar and bounded meaning checks. These code and wording checks do not include a native-speaker human review, professional translation certification or evaluation with Spanish broadcast users.

| Concept | Reviewed Spanish | Meaning constraint |
| --- | --- | --- |
| Synthetic match | partido sintético | Clearly fictional data, not a real match feed. |
| Missing/invalid current model choice | sin selección válida del modelo | Describes the selection gate; does not suggest model prose was accepted. |
| Pressure events | acciones de presión | Counts recorded actions, without establishing effectiveness or tactics. |
| One possession regain | 1 recuperación del balón | Singular form; regains plural when the count differs. |
| Pressure causal qualification | Solo describe actividad; no demuestra que la presión causara las recuperaciones. | Explicitly avoids turning co-occurrence into causation. |
| Shots on target | tiros a puerta | Uses the recorded on-target flag, not expected goals. |
| No causal/xG claim | sin xG ni afirmación causal | No generated estimate or causal finding. |
| Zero denominator | no disponible (0 intentos/tiros) | Does not turn an undefined rate into zero. |
| Inclusive time window | ventana temporal inclusiva | Both timestamp endpoints count. Existing exact numeric formatting is preserved. |
| Saved model selection | selección registrada; evidencia histórica | A receipt-backed prior selection, not new inference or a current live claim. |

Spelling was cross-checked against RAE entries for [presión](https://dle.rae.es/presi%C3%B3n), [sintético](https://dle.rae.es/sint%C3%A9tico) and [táctico](https://dle.rae.es/t%C3%A1ctico). These dictionary entries support spelling; the football/data meaning review comes from the actual event and metric contract.

Historical M3 validation: all 30 original core tests plus 5 language tests passed. In that reviewed change, every fixture snapshot/digest, every non-text Spanish card field and every complete English card remained equal to the M2 baseline. This does not assert equality or a test result for later source changes. Short Spanish cards remain within 35 words. A fixture-checked example is `3 acciones de presión y 1 recuperación del balón en 50s`; it does not incorrectly describe the clipped initial window as 60s.

The review also recommended accented forms, singular/plural recorded moments, `selección registrada`, clear historical-only wording and verified goal withdrawals in the recap. Recap validation is separate from the template results above. No new model call was used for this review.
