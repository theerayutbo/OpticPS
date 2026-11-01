# NANF fibre model: scope, equations and validity (Gate N1)

Written 2026-10-31. Scope: the profile-driven linear propagation added to `optical_channel/fiber.py` and
`optical_channel/link.py`. Derived from the wave equation and the sources in `docs/NANF_SOURCES_AND_PROVENANCE.md`;
no simulator code was consulted. Nothing here is a fit, a score or a simulation of a paper's curve.

## 1. What is modelled

A single-polarisation, single-mode, linear fibre acting on the complex optical envelope A, with
E = A exp(-i omega0 t), before square-law detection. A component at optical offset omega obeys

    dA/dz = -(alpha/2) A + i (beta2/2 omega^2 + beta3/6 omega^3) A

so after length L the amplitude is multiplied by 10^(-alpha_dB L / 20) (power by 10^(-alpha_dB L / 10), alpha_dB
in dB/km) and the phase by exp(i (beta2/2 omega^2 + beta3/6 omega^3) L). Square-law detection, noise and the
modulator are the validated `transmit` code, unchanged. A resolved profile becomes an ordinary `LinkConfig`, so the
G.652.D route and the profile route share one implementation (a test shows the two are equal bit for bit).

| Element | Handling |
|---|---|
| Distributed attenuation | alpha_dB x L, from a scalar or a table, in power; applied to the field as an amplitude |
| Connector, pigtail, splice | separate dB components, summed once, applied once as lumped loss; never inferred from the link-loss envelope |
| Chromatic dispersion | all-pass phase; D and optional S in ps/(nm km) and ps/(nm^2 km) |
| Group delay | tau = n_g L / c, carrier delay only; it does not change the intensity |
| Tables | optional loss and D tables; linear interpolation inside the knots |
| Power protocols | `fixed-launch-power` and `matched-received-power` (section 4) |

## 2. Equations (derived here)

1. D = d(1/v_g)/d(lambda) and beta2 = d^2 beta / d omega^2 give D = -(2 pi c / lambda^2) beta2, so
   beta2 = -D lambda^2 / (2 pi c). Check: D = 17 ps/(nm km) at 1550 nm gives -21.68 ps^2/km.
2. Let S = dD/d(lambda), lambda = 2 pi c / omega, d lambda / d omega = -lambda^2 / (2 pi c). Then
   beta3 = d beta2 / d omega = [d/d lambda of (-D lambda^2 / (2 pi c))] x [d lambda / d omega]
   = [-(S lambda^2 + 2 D lambda) / (2 pi c)] x [-lambda^2 / (2 pi c)]
   = (lambda^4 S + 2 lambda^3 D) / (4 pi^2 c^2).
   The 2 lambda^3 D term is not an option: any given slope, including 0.0, carries it. An omitted slope means
   second-order dispersion only, and the resolved record says `slope_omitted_second_order_only`.
3. Small-signal intensity response of a chirp-free DSB link: |H(f)| = |cos(pi lambda^2 D L f^2 / c)|, first null
   f1 = sqrt(c / (2 lambda^2 D L)). The slope S leaves the null unchanged at first order.

## 3. Units, sign and FFT order

SI inside; D in s/m^2 (1 ps/(nm km) = 1e-6 s/m^2), S in s/m^3 (1 ps/(nm^2 km) = 1e3 s/m^3). numpy's FFT kernel is
exp(-i omega t), so numpy's frequency axis is the negative of the physical offset: the even beta2 term is unchanged
and the odd beta3 term enters as exp(-i beta3 L omega_np^3 / 6) (in the validated `dispersive_field`). Sign test:
D > 0 delays the longer wavelength (tested with two carriers; it reverses for D < 0).

## 4. Power protocols

- fixed-launch-power: the laser power of the base config is used; the received power follows from the loss.
- matched-received-power: the laser power is set so the mean received optical power equals the stated dBm, whatever
  the loss. The compensation is a gain on the launch side, so the signal and noise statistics equal those of a
  variable attenuator at the receiver set to the same received power. The result records the protocol.

## 5. Validity and refusal rules

- Every scalar is valid at its stated validity range, else at its measurement wavelength only, else (neither stated)
  at any wavelength, except the wavelength-dependent ones: D, S and the attenuation raise `OutOfValidityRangeError`
  when they state no wavelength at all, because applying them at an unknown wavelength is a guess. The check applies
  to every parameter a run uses. A wavelength outside raises. Tables are valid between their first and last knot.
  Extrapolation happens only if requested; then tables continue their end segment and the names are listed in
  `extrapolated` (truthful: only names outside their range are listed).
- Dispersion law, one rule for every source of S (profile or scenario): D(lambda) = D_stated + S (lambda - lambda_stated),
  where lambda_stated is the `measurement_wavelength_nm` D was measured or stated at. `reference_wavelength_nm` is the
  carrier or nominal wavelength only and never anchors D (an unknown reference changes nothing). It holds inside the
  stated range and, under requested extrapolation, beyond it (no clamp). Example (own numbers): D 10 stated at 1550,
  range 1500 to 1600, S 0.06 gives 10.0 at 1550 and 12.4 at 1590 for any reference wavelength, and, extrapolated, 14.2
  at 1620. A scenario S places a known D the same way (Wang, D 4.42 stated at 1550, scenario S 0.06, 1560 extrapolated:
  5.02). A D that has a validity range but no single measurement wavelength cannot take an S: that raises. Without S, D
  applies only at its stated wavelength or inside its stated range and is held there (recorded as second order only);
  D is never held across wavelength when an S is known. A scenario D that has any S in force (the profile's or a
  scenario's) must state its wavelength (`SensitivityScenario.dispersion_wavelength_nm`), which anchors it exactly like a
  `measurement_wavelength_nm`; without it the S is refused (`OutOfValidityRangeError`). A scenario D with no S in force is
  taken as D at the requested wavelength and recorded as second order only. A measurement wavelength that lies outside
  its own validity range is refused when the provenance is built.
- Table against scalar: where a table and a known scalar both hold at the requested wavelength they must agree (relative
  1e-6), else the profile must declare which wins in `precedence` (per field: `table` or `scalar`, with a real citation
  and provenance); the result records the declared winner and its provenance in `sources`. Without a declaration it
  raises. A known S (or a scenario S) that disagrees with the local slope of the D table in force (beyond 1e-3 plus 10%
  of the table slope, ps/(nm^2 km)) is refused; only a known S may be declared the winner. A scenario S never overrides a
  table, under any declaration: it is refused when it disagrees with the table slope, and also when it places a known
  scalar D away from the D table (even if the profile declared the scalar the winner over the table). The declaration is
  tracked as a flag, not read from the source text of D.
- An unknown value raises `MissingFiberPropertyError` and the message says no default is substituted. The only way to
  run is a `SensitivityScenario` with a label; it may fill unknown values only, never override a known one, and it is
  recorded in the result. Scenario values obey the same physical minima as known values (losses not negative,
  group index at least 1). The label travels with the numbers: `profile_link_config` carries it into `LinkConfig`,
  `transmit` metadata, `propagate_profile_field` (a `ProfileField` with the record) and `transmit_profile`. The
  `transmit` metadata also keeps `profile_id`, `sources` and `extrapolated`. `not_a_benchmark_result: true` is set for
  any profile run that used a scenario-filled or an extrapolated value, whether or not a scenario was named. A label
  already on the base `LinkConfig` is kept in the config and in the link record that `transmit_profile` returns (with
  `not_a_benchmark_result`), never silently replaced (a different scenario label raises) and a blank one raises. The profile route also refuses a base `extra_attenuation_db` that is not finite or is negative; the G.652.D
  route is unchanged.
- Loader: a table must be in dB/km (loss) or ps/(nm km) (D). A `measured` or `published-*` value needs a real
  citation: at least 6 non-space characters, at least 4 distinct characters, and at least one word that is not a
  placeholder or filler (none, n/a, tbd, to be determined, citation needed, see the paper, missing data, will add later,
  digits only and similar), in any script. This is a form floor only; it cannot tell whether the cited place exists. It
  admits short non-sense such as "asdfgh", "abc123", "Table 2" and "to_be_determined" (one word), and the floor is not
  being raised: a real citation is a matter for review, not for a regular expression.
- matched-received-power refuses a non-finite target and a target above 10 dBm (a sanity limit: above it the laser and
  detector would be outside anything modelled, so the number is taken to be a mistake). It is not the owner's -5 dBm
  Hong receiver limit, which is not enforced here. The refusal does not depend on any scenario. The laser power the
  matched protocol then needs is bounded too: above 1 W (30 dBm) it raises, so a huge loss is refused instead of
  returning an absurd power. A loss so large that the transmission underflows to zero (about 10000 dB) is the same
  refusal with the same message, never a `ZeroDivisionError`.
- Kerr, inter-modal coupling, gas absorption and amplifier (EDFA) noise are unsupported. A profile that sets one `on`,
  or a call that lists one in `effects`, raises `UnsupportedEffectError`. `gamma` is stored and never active.
- Chirp is not part of this gate. A transmitter chirp parameter is a separate question (plan Amendment 1, A1).

## 6. What the profiles hold, and what stays unknown

| Profile | Known | Unknown (raises) |
|---|---|---|
| NANF-HONG-2021-4P76KM | L 4.76 km; D 2.04 at 1550 (`published-numerical-assumption`); S 0.004 (`derived`); n 1.003; pigtails ~2 dB; NANF-NANF splice ~0.1 dB; geometry; total link-loss envelope 6.45 to 8.33 dB over S+C+L (informational, not assigned to 1550) | distributed attenuation (pending the N2 gate), connector loss, gamma |
| NANF-ALTUNA-2024-3P1KM, -11P1KM | length and the 1480 nm PoF transmission (37.2%, 3.6%) as `user-assumed`, kept only as a context measurement | 1550 attenuation, D, S, all lumped losses, group index. No geometry values were supplied to this gate |
| NANF-WANG-2025-2P032KM | L 2.032 km, D 4.42, gamma 0.007 at 1550, all `user-assumed` | attenuation, lumped losses, S, group index; separate record; sample identity unknown; no coherent workflow |
| ITU-G652D-REFERENCE | the existing `g652d_preset`, unchanged | none |

Altuna and Wang values come from the owner brief; only the Crossref identity of each paper was read. They are tagged
`user-assumed` with the note "stated in owner brief, not read from paper" and stay so until the primary paper is
read. Which physical spool any record used is not asserted: the 11.1 km Altuna record and the CLEO 2025 abstract may
share one, and each record stays separate.

## 7. Limits

- N2 must not count a scenario `connector_loss_db` together with the Hong pigtail figure of about 2 dB: that figure
  already covers the connectorisation, so a connector scenario on top would count the same loss twice.

- The Hong D is one assumed value at 1550 nm with a derived slope; it is not a measurement of the spool and it is not
  a wavelength curve. A wavelength sweep (plan B2, C5) needs a D(lambda) table, which is N2 work.
- No attenuation of any NANF profile is known, so no complete NANF link runs without a labelled scenario.
- Linear and scalar: no polarisation-mode dispersion, no Kerr, no noise from the fibre, no mode coupling; a
  hollow-core fibre's gas absorption and inter-modal beating are real effects that are not modelled and are not
  claimed to be negligible. Results are model checks, not validation.
- Pre-registered zero-chirp null check (plan A1.3, tolerance 0.3 GHz), from this propagation model with square-law
  detection of a small-signal tone: SSMF D 15.95, L 4.53 km: 29.386 GHz (29.39); L 5 km: 27.970 GHz (27.97); NANF
  D 2.04, L 4.76 km: 80.158 GHz (80.2). Agreement is within 0.05 GHz. This tests the simulator, not the paper.

## 8. The simulation chain of Gate N3 part a (synthetic only)

Written 2026-11-01. Scope: `measurement/nanf_chain.py`, `receiver/dfe.py`, `measurement/nanf_scoring.py`, `measurement/nanf_freeze.py`. Nothing here is a fit, a score of the paper's curves, or a validation; no workbook value was read in this gate.

**What the chain models.** PAM4 symbols, SRRC shaping with roll-off 0.1, an 8-bit DAC at 70 GSa/s, ideal band-limited up-sampling to a 280 GSa/s analogue grid, a 4th-order Butterworth (zero-phase magnitude) Tx filter, the existing sine-law MZM, the existing profile propagation (all-pass dispersion, loss), square-law detection with shot and thermal noise, the Rx filter, ideal band-limited resampling to the 80 GSa/s scope, an additive white electrical SNR ceiling, exact rational resampling to 2 samples per symbol, an SRRC matched filter, and a T/2 (17, 7) RLS DFE (17 feed-forward taps, 7 feedback taps, lambda 0.998, 8192 training symbols then decision-directed). BER is bit-error counting over 647008 scored symbols (1 294 016 bits); SNR is plan B6. The sample grid needs a multiple of 140 symbols (F1) and refuses anything else.

**Declared assumptions (all `user-assumed`, plan F4 and F6).** Zero chirp; no RIN; ideal AWG reconstruction and ideal scope resampling (brick wall, no aliasing, no scope quantisation or jitter); zero timing phase; zero-phase filters; extinction ratio 30 dB; matched received power; the DFE tap split, cursor, training and initialisation of F6. The SSMF SNR is biased optimistically by the missing level-dependent intensity noise and by the phase-to-intensity conversion of laser phase noise (F3); the size is unknown.

**Validity and known behaviour.**

- The first null reproduced through the full analogue path in tone mode agrees with the closed form to better than the 0.3 GHz of plan A1.3 (SSMF 4.53 and 5 km, NANF 4.76 km); this checks the path, not any fibre.
- The DFE is checked on synthetic ISI channels: noise-free it removes the ISI to 143 to 175 dB output SNR (the test bound is 80 dB) with zero decision errors, and at a spectral null with 27 dB channel SNR it has no decision errors where a 17-tap linear FFE has a symbol error rate near 0.18. On AWGN the slicer and a one-tap RLS match the Gray PAM4 Q-function expressions within 2 binomial standard deviations (z from -1.5 to 1.9 at BER 1.6e-3 to 2.7e-2).
- The trace cap of the RLS is pinned at 1e10 (plan Amendment 6 G1). On the real chain with the mid-point vector (synthetic) the largest trace(P) is 1.1e8 to 8.3e8 at every run that holds lock (see the next paragraph for those that do not), so at 1e10 the cap never acts (`n_trace_caps == 0`) and the equaliser is the plain lambda = 0.998 RLS of the paper; a test compares cap 1e10 with no cap on a full-size point and finds them identical. The earlier default of 1e4 was wrong: it acted on 653470 of 655200 symbols (a band-limited T/2 input leaves part of the 24-dimensional regressor space almost empty, so trace(P) sits at the cap), turned the equaliser into a constant-trace RLS and moved the bit errors by 8 to 23 percent (BER 3.585e-3 against 3.975e-3 at 100 Gb/s back-to-back, -9 dBm: opposite sides of the 3.8e-3 threshold). The earlier text of this section said 3 percent between 1e4 and 1e8 and implied the cap was needed to stop an overflow; both were wrong for the real chain, where P stays bounded while the equaliser holds lock. A cap of 1e8 was the worst choice: it acted part of the time and made the result depend on the cap. A run in which the cap acts is invalid and can never be scored.
- The pinned equaliser can lose lock at low received power. In a synthetic sweep of 3 rates x 3 links x ROP -16 to -5 dBm in 1 dB steps (mid-point vector), 22 of 108 runs did not hold lock: the decisions collapse and trace(P) grows past 1e10, so either the cap acts (tens of thousands to half a million times; BER 0.23 to 0.47, SNR near 0 dB) or P loses positive definiteness and `RlsInstabilityError` is raised. Every one of them lies at least 3 dB below the 3.8e-3 crossing of its own curve, at the noise-limited end where the curve is above BER 0.05. Runs that hold lock have trace(P) of 1.1e8 to 8.3e8 at the mid-point vector (1.2e9 at most at the corners of the B4 box, where the corner with 10 GHz bandwidths, modulation depth 0.2 and a 15 dB ceiling lost lock at 17 of 18 points, even at -5 dBm, because the received spectrum is nearly empty above 15 GHz). Such a run is invalid and is not scored. Whether a published ROP axis contains such points was not checked (no workbook axis was read); the plan does not yet say how a criterion that needs such a point is read, and a calibration that visits such a vector must treat the failed run as an invalid evaluation (reported in the N3a fix round handoff).
- `np.clip` to [-1, 1] is applied to the waveform after the band-limited up-sampling to the 280 GSa/s grid and before the Tx filter (the up-sampled quantised waveform can overshoot full scale by the Gibbs ringing of the brick-wall interpolation). F4 does not declare this step; it is declared here and in Amendment 6 G9, `user-assumed`, and is not a free parameter.
- Cost: one full-size point (655200 symbols) takes about 14 s on one core of the development machine, of which about 12 s is the RLS loop.
- Not modelled: OFDM, chirp, RIN, laser phase noise, polarisation, TIA nonlinearity above -5 dBm, scope noise other than the ceiling. The propagation model refuses a wavelength outside the validity range of any profile property it needs, as before.
