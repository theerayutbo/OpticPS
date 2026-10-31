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
  D is never held across wavelength when an S is known. A scenario D is taken as D at the requested wavelength.
- Table against scalar: where a table and a known scalar both hold at the requested wavelength they must agree (relative
  1e-6), else the profile must declare which wins in `precedence` (per field: `table` or `scalar`, with a real citation
  and provenance); the result records the declared winner and its provenance in `sources`. Without a declaration it
  raises. A known S (or a scenario S) that disagrees with the local slope of the D table in force (beyond 1e-3 plus 10%
  of the table slope, ps/(nm^2 km)) is refused; only a known S may be declared the winner, and a scenario can never
  override a table.
- An unknown value raises `MissingFiberPropertyError` and the message says no default is substituted. The only way to
  run is a `SensitivityScenario` with a label; it may fill unknown values only, never override a known one, and it is
  recorded in the result. Scenario values obey the same physical minima as known values (losses not negative,
  group index at least 1). The label travels with the numbers: `profile_link_config` carries it into `LinkConfig`,
  `transmit` metadata, `propagate_profile_field` (a `ProfileField` with the record) and `transmit_profile`. The
  `transmit` metadata also keeps `profile_id`, `sources` and `extrapolated`. `not_a_benchmark_result: true` is set for
  any profile run that used a scenario-filled or an extrapolated value, whether or not a scenario was named. A label
  already on the base `LinkConfig` is kept, never silently replaced (a different scenario label raises) and a blank one
  raises. The profile route also refuses a base `extra_attenuation_db` that is not finite or is negative; the G.652.D
  route is unchanged.
- Loader: a table must be in dB/km (loss) or ps/(nm km) (D). A `measured` or `published-*` value needs a real
  citation: at least 6 non-space characters, at least 4 distinct characters, and at least one word that is not a
  placeholder or filler (none, n/a, tbd, to be determined, citation needed, see the paper, missing data, will add later,
  digits only and similar), in any script. This is a form check only; it cannot tell whether the cited place exists.
- matched-received-power refuses a non-finite target and a target above 10 dBm (a sanity limit: above it the laser and
  detector would be outside anything modelled, so the number is taken to be a mistake). It is not the owner's -5 dBm
  Hong receiver limit, which is not enforced here. The refusal does not depend on any scenario. The laser power the
  matched protocol then needs is bounded too: above 1 W (30 dBm) it raises, so a huge loss is refused instead of
  returning an absurd power.
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
