Owner-supplied retrospective note, produced outside the Crew after the A2 record; it does not change the A2 record or any tolerance.

# A2 endpoint decomposition (retrospective)

This note does not change the A2 record. `law_model_v2.yaml` stays `FIT_INVALID, S2 not evaluable`.
R6 was not computed. No optimiser was run. `f(v)` and AC4 are unchanged. The v1 verdict
`CLOSE_PARTIAL` at S2 stays the verdict of record.

The two saved `poly` ends were evaluated once each on the fit windows only: B2B at amplitude 1 and
2 km at amplitude 0.832, fit seed 20261111, 1048576 synthetic samples, the same joint loss as the
fit. The spread and evaluation windows were not read. The 10 km file was not read. Its access time
stayed 2026-10-31 16:30:05. The B2B and 2 km access times moved to 2026-11-13 00:48:57 and
00:48:58 because those two fit windows were read.

Both recomputed sums match the stored objectives exactly (difference 0).

## Start 3, the reported optimum, stored J = 0.140582285876315

| window | M1 | M2 | M3 | M4 (dB) | 0.05 M4 | window J |
|---|---:|---:|---:|---:|---:|---:|
| B2B fit | 0.015831909814480 | 0.014712925497281 | 0.018269831948466 | 0.590830397099776 | 0.029541519854989 | 0.078356187115216 |
| 2 km fit | 0.000318226080327 | 0.012423695054454 | 0.014947080360738 | 0.690741945311602 | 0.034537097265580 | 0.062226098761099 |

## Start 10, stored J = 0.141589458634261

| window | M1 | M2 | M3 | M4 (dB) | 0.05 M4 | window J |
|---|---:|---:|---:|---:|---:|---:|
| B2B fit | 0.013336206916551 | 0.014239967407680 | 0.019003190943451 | 0.611530008024753 | 0.030576500401238 | 0.077155865668920 |
| 2 km fit | 0.003673328534789 | 0.011860548958999 | 0.013883595672237 | 0.700322395986340 | 0.035016119799317 | 0.064433592965341 |

## Start 10 minus start 3

| window | M1 | M2 | M3 | 0.05 M4 | window J |
|---|---:|---:|---:|---:|---:|
| B2B fit | −0.002495702897928 | −0.000472958089601 | +0.000733358994984 | +0.001034980546249 | −0.001200321446296 |
| 2 km fit | +0.003355102454462 | −0.000563146095455 | −0.001063484688501 | +0.000479022533737 | +0.002207494204242 |
| both | +0.000859399556534 | −0.001036104185056 | −0.000330125693517 | +0.001514003079986 | +0.001007172757946 |

The objective gap 0.001007172757946 is the net of a B2B improvement of 0.001200 and a 2 km
worsening of 0.002207. The largest single adverse term is the 2 km level spacing, M1
+0.003355. The largest single favourable term is the B2B level spacing, M1 −0.002496. M2 improves
on both windows. M3 worsens at B2B and improves at 2 km. The weighted spectrum term worsens on
both windows and contributes +0.001514 before the other terms cancel most of it.

These are fit-window residuals of two saved parameter vectors. They are not an R6 score, not a
sensitivity matrix, and not a basis for a new AC4 tolerance.
