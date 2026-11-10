# History rewrite of `main..v1.3-mpam` (2026-11-10)

Date: 2026-11-10. Author of the rewrite: Dev (Crew), reviewed separately by Aria before any push.

## Reason

The unpublished history of the branch `v1.3-mpam` (82 commits above `main` at `a2eb969`) held two kinds of
content that must not reach a public MIT repository:

1. Licence. Verbatim sentences of one CC BY-NC-ND 4.0 journal article (the Ran et al. Nat Commun 2025
   article, see `docs/benchmarks/SOURCE_REGISTER.md`, "Licence conflict"). The tip had already been cleaned
   (E0 fix round 2, `0424e9c` old id); the sentences remained in older versions of three files.
2. Instrument serial. An oscilloscope serial number read from a capture header was recorded in one
   documentation file in three commits and was removed from the tip at `536b3ec` (old id), but stayed in history.
   The model string (`UXR0704AP`) is kept.

No offending text is written in this file, in the commit messages or in the handoff. Only commits, paths and line
positions are named.

## Tool

`git-filter-repo` 2.47.0 (pip, scratch virtualenv outside the repository; not shipped with the project),
Git 2.50.1. Run with `--refs refs/heads/v1.3-mpam` so only the branch was rewritten, and a blob callback:

- the serial was replaced by the marker `[instrument serial removed]`;
- every run of words that matches a hashed word window of the removed article sentences (the
  7-word SHA-256 windows already committed in `tests/test_benchmark_provenance.py`, `REMOVED_ARTICLE_WINDOWS`)
  was replaced by `[article text removed: CC BY-NC-ND]`. The detector used only those hashes, so no sentence
  was written to any file. Neighbouring words and short phrases below the window length were left unchanged.

The helper script and its input files were kept in scratch and deleted. filter-repo also rewrites the
abbreviated commit ids that appear in commit messages to the new ids (one subject changed this way, `E2a fix round`).
File contents are not rewritten beyond the two replacements: ids written inside files (plans, handoffs,
`CHECKPOINT.md`, comments in tests) still carry the OLD ids; use the map below.

## Scope

- `main` (`a2eb969`) and its tags are untouched.
- 65 of 82 commits have final ids that differ from the original ones: 21 changed in content, the others only because an ancestor changed or because of the mailmap step below.
- The tree of the tip is identical to the old tip's tree (`git diff` of the two tips is empty): the offending text
  existed only in older versions of files.

Affected paths and commits (original id -> final id):

- Serial: `docs/benchmarks/MISSING_PARAMETERS.md`, line 110 of the versions in `12eb480` -> `5ebafae`, `5713ed5` -> `a01a7e5`, `b7f4ac0` -> `1f530b2`.
- Article text: `configs/benchmarks/ran_2025_g652d.yaml`, `docs/benchmarks/SOURCE_REGISTER.md`, `tests/test_benchmark_provenance.py` and (short fragments, third pass) `docs/orchestration/opticps-v2/handoff/E0_qa2.md`, in `70dc3b2` -> `63b6d6b`, `51b411e` -> `9a26bc2`, `94a3ec9` -> `72101ec`, `9a891c9` -> `523867e`, `f73c1cc` -> `54ed3c6`, `4a08c48` -> `39a8fbb`, `8f57af9` -> `7d357b8`, `843d223` -> `1ce54c4`, `f5f9bef` -> `a6883ba`, `eba060a` -> `add4ba2`, `ee74d05` -> `f14e31c`, `ba367cc` -> `3ebc9cf`, `8f8fc7a` -> `8be3000`, `b54cc18` -> `6176e2f`, `6d75b88` -> `78434d2`, `0424e9c` -> `cc05d17`, `47890a6` -> `1bfdb4f`, `97b653d` -> `610fa45`.

## Second step: author and committer address

Seven commits carried an author or committer email made of the local user name and the local hostname. A second
`git-filter-repo --mailmap` run (branch only, `main` untouched) mapped that address to the noreply address used on `main`
and on the other 75 branch commits, keeping the name. The tables below map each ORIGINAL pre-rewrite id to its FINAL id
after both steps. After the step, all 164 author and committer fields above `main` use the noreply address.

## Third step: two short fragments

An independent review found two short quoted fragments of the article text that the 7-word detector could not see: a
6-word phrase in `docs/benchmarks/SOURCE_REGISTER.md` line 93 (7 snapshots) and a 5-word sentence opener in
`docs/orchestration/opticps-v2/handoff/E0_qa2.md` line 14 (from its first commit to the tip). A third
`git-filter-repo --replace-text`-equivalent pass (branch only) replaced both with `[article text removed: CC BY-NC-ND]`.
The tables map each ORIGINAL id to its FINAL id after all three steps.

## Backup

The original history is kept only as the local ref `refs/backup/pre-rewrite-v1.3-mpam` (old tip
`138569239e656e3a10d8fb7378dff36d84ba1b13`) in the rewritten clone, and in the original checkout. It was never published: `origin` holds only `main` at
`a2eb969`. Do not push `refs/backup/*`, do not use `--mirror` or `--all`; push the branch `v1.3-mpam` only.

## Original -> final commit ids (82 commits, oldest first; the documentation commits come after)

| original | final | change | subject |
|---|---|---|---|
| `f5f271f` | `f5f271f` | unchanged | Add Gate 0 audit docs and PAM4 byte anchor |
| `de1fc73` | `de1fc73` | unchanged | Address Loki review of C1 |
| `2edb78b` | `2edb78b` | unchanged | Tighten C1 anchor and correct gap matrix rows |
| `a9ac612` | `a9ac612` | unchanged | Generalise rates.py to PAM-M and add independent rate tests |
| `2522755` | `2522755` | unchanged | Address Loki review of C2 |
| `c51b331` | `c51b331` | unchanged | C3: symmetric pair family, entropy-matched MB, symmetric CCDM quantiser, profiling |
| `e3502e5` | `e3502e5` | unchanged | C2: common-grid Gauss-Legendre integrator for unequal sigma, PAM4 spread guard |
| `e65d1a9` | `e65d1a9` | unchanged | C3 review fixes: typed try_decode failures, silent-misdecode limit, doc corrections |
| `5a851dd` | `5a851dd` | unchanged | C3 second review: correct silent-misdecode statistics and n lists, pin error hierarchy |
| `45eafdf` | `45eafdf` | unchanged | C4a: rates.py review minors (dead-level sigma spread, order-aware warning, pinned grid con |
| `2b9e1fe` | `2b9e1fe` | unchanged | C4: generic symmetric optimiser, best-fixed menu, constraints, acquisition guard |
| `d9ba016` | `d9ba016` | unchanged | C4 fix round: floor 1/n, direct uniform at zero loss, recomputed acquisition hash, checked |
| `aed1a5c` | `aed1a5c` | unchanged | Crew: record C3 and C4 gates |
| `19a96a4` | `19a96a4` | unchanged | C5a: C4 review leftovers (FixedOMA edges, mutation tests, honest labels, note) |
| `908dd0c` | `908dd0c` | unchanged | C5: M-PAM frame, profiles config, export schema v2, validator |
| `8129eca` | `8129eca` | unchanged | C5 fix round: enforced reportable, fixed evidence label, validator recomputation, default- |
| `8900748` | `8900748` | unchanged | E0: declare TERIPHIC fit/holdout plan before any sample is read; ignore data/external |
| `70dc3b2` | `63b6d6b` | content | E0: source register, missing-parameter matrix, provenance schema, strict catalog loader, b |
| `51b411e` | `9a26bc2` | content | Crew: record C5 gate |
| `94a3ec9` | `72101ec` | content | E0: handoff and final test record |
| `9a891c9` | `523867e` | content | N0: declare NANF fit/holdout plan before any data cell is read |
| `f73c1cc` | `54ed3c6` | content | N0: NANF sources, schema and provenance record, offline test, status entries |
| `4a08c48` | `39a8fbb` | content | N0: handoff |
| `8f57af9` | `7d357b8` | content | E0 fix: Revision 1 of the TERIPHIC fit/holdout plan (shared sequence, all-statistic locks, |
| `843d223` | `1ce54c4` | content | N0 fix: Amendment 1 to the NANF fit/holdout plan (chirp nuisance, B2B-copy comparator, pre |
| `f5f9bef` | `a6883ba` | content | E0 fix: typed constructors, strict loader, untypeable VERIFIED, leakage on all identities, |
| `eba060a` | `add4ba2` | content | E0 fix: handoff, fix round and mutant list |
| `ee74d05` | `f14e31c` | content | N0 fix: corrected NANF sources record, content-based third-party guard, fix-round handoff  |
| `ba367cc` | `3ebc9cf` | content | Crew: record N0 gate and E0 reviews |
| `8f8fc7a` | `8be3000` | content | N1 step 1: plan Amendment 2 (C1 cases, C5 range, A2 d vs own no-fibre, B2B gate, A1.7 rang |
| `b54cc18` | `6176e2f` | content | N1: NANF fibre profiles with provenance, profile-driven coherent propagation, configs, tes |
| `6d75b88` | `78434d2` | content | N1 fix round: slope path from reference wavelength, scenario minima and label, loader stri |
| `0424e9c` | `cc05d17` | content | E0 fix round 2: byte-compared freeze guard with history check, plan Revision 2, licence an |
| `47890a6` | `1bfdb4f` | content | E0 fix round 2: handoff |
| `97b653d` | `610fa45` | content | N1 fix round 2: D anchored at its stated wavelength for every S source, wavelength-bound r |
| `8b84914` | `10e7554` | sha only | E0 fix round 3: narrowed freeze-guard promise, fixed criterion path, whole-criterion signa |
| `638dc3a` | `0c10e91` | sha only | Crew: record N1 gate and E0 third review |
| `fc22f41` | `e144a50` | sha only | E0 fix round 3: status record with final pin and counts, pending review |
| `e8048ed` | `b5b558e` | sha only | N2a: close N1 minors (boolean slope gate, scenario S never overrides a table, scenario D s |
| `4c81691` | `e240a02` | sha only | N2a: mutation script, match the formatted slope guard (28 of 28 killed) |
| `d52149a` | `4ce6bd1` | sha only | E0 fix round 4: full-history merge routes, symlink refusal, plan Revision 4, known-limits  |
| `ba55025` | `78aff91` | sha only | N2: stdlib NANF workbook importer (SHA-256, default-deny schema, holdout withheld), Fig.1  |
| `f4bfeaa` | `9148930` | sha only | Crew: record E0 closing reviews |
| `57643ca` | `612778f` | sha only | E1a: plan Revision 5 (retraction corrected, new pin), local hashes verified, known limits  |
| `7bd6ab9` | `9122875` | sha only | N2 fix round: withdraw false >60 GHz mismatch, per-wavelength loss bound, measured evidenc |
| `12eb480` | `5ebafae` | content | E1: read-only external capture reader, B2B format verification, fractional-sps timing, str |
| `5713ed5` | `a01a7e5` | content | Crew: record N2 first-part gate |
| `b7f4ac0` | `1f530b2` | content | N3 step 1: plan Amendment 5, N2 leftovers closed, QA5 survivors killed |
| `536b3ec` | `c51f9b3` | sha only | E1 fix round: one holdout gate for every route, physical pass apart from structure, plan R |
| `b7eaab5` | `7cb3d84` | sha only | N3a: RLS DFE, NANF simulation chain, C1-C8 scoring, identifiability, freeze-gated holdout  |
| `936337d` | `3a21f8a` | sha only | E1 second fix round: CLI routes gated by a walked list, whole-record block pass, plan Revi |
| `bd5a557` | `7b6498d` | sha only | E1 second fix round: tests for the clipping, distinct-value and changed-file guards, mutan |
| `39d2506` | `fbb2323` | sha only | N3a fix round: plan Amendment 6, trace cap pinned at 1e10, default deny, freeze binds a co |
| `c7066f0` | `db18769` | sha only | N3a fix round: mutant script runs the fast test files first |
| `263926a` | `44c7168` | sha only | N3a fix round: tests for seven surviving freeze guards, four equivalent mutants removed fr |
| `9778ce8` | `b0118ab` | sha only | E1 third fix round: route claim narrowed to typed CLI options, plan Revision 8, block pass |
| `ae9add3` | `5769469` | sha only | E1 third fix round: test that a change before the pass is refused before any block is read |
| `d4a50d6` | `3ba777e` | sha only | N3a: plan Amendment 7, lost-lock runs are invalid, reported, and never help a score |
| `869effc` | `5404700` | sha only | N3a Amendment 7: tests for two surviving mutants (all points lost reason, infinite evaluat |
| `dafa062` | `3685f58` | sha only | N3a: Fix round handoff with the Amendment 7 summary and final gate counts |
| `1e1e90a` | `da0f2eb` | sha only | E1 closing round: require_frozen_criterion stated as an E2 obligation, shrinking-file word |
| `43402f7` | `7811bce` | sha only | Crew: record Gate E1 reviews and PASS |
| `c0b7886` | `62d4597` | sha only | E2a: scoring entry point, frozen estimators, B2B surrogate, B2B-only model and pre-registe |
| `1b496d2` | `3fca819` | sha only | E2a: plan Revision 10, scoring entry point, model, frozen criterion definition, code ident |
| `d520ff7` | `dbd549f` | sha only | E2a: freeze the TERIPHIC criterion (plan Revision 10) |
| `5b504b7` | `7e58784` | sha only | E2a fix: bind the freeze to its inputs, selected scenario added once, new criterion path |
| `9976d3b` | `2dce775` | sha only | E2a: plan Revision 11, freeze bound to its inputs, first freeze superseded |
| `007b8b2` | `ec1ac97` | sha only | E2a: freeze the TERIPHIC criterion at the R11 path (plan Revision 11) |
| `df7fdc1` | `0f3539b` | sha only | E2a: Dev handoff |
| `6d46ecb` | `bee0c43` | sha only | N3a second review: plan Amendment 8, holdout record corrected, Fig.11 excluded, guards clo |
| `de6ee5e` | `2405965` | sha only | N3a second review: ascending-eigenvalue test, one equivalent mutant removed from the list |
| `6b4939b` | `f86edd3` | sha only | N3a second review: Fix round handoff with the Amendment 8 summary and final counts |
| `9b1e7a3` | `e039d97` | sha only | E2a fix round (review FAIL at 0f3539b): governance fixes, gain-invariant two-stage criteri |
| `b9dec83` | `4da3755` | sha only | E2a: plan Revision 12 (R11 reviewed, failed and never scored), review E2a_qa.md |
| `8a81907` | `04360ec` | sha only | E2a: freeze the TERIPHIC criterion at the R12 path (plan Revision 12) |
| `07b7d1a` | `776b5c6` | sha only | E2a: Dev handoff after the fix round |
| `ee1daa3` | `b8c4838` | sha only | E2a: tests for a register MD5 mismatch alone (mutant md5_not_required), before and after t |
| `2307db2` | `0c674c9` | sha only | N3a closing review: plan Amendment 9, calibration flag checked, grafts from the common dir |
| `131c3a1` | `a2e8c0c` | sha only | N3a closing review: tests for two surviving calibration-path mutants |
| `4cedbd1` | `63ad237` | sha only | E2a: tests for the survivors of the end-to-end mutant run (pin format, first-parent line,  |
| `8120b8a` | `1107616` | sha only | Crew: pause checkpoint; record N3a reviews 1-3 and E2a state |
| `1385692` | `d76b730` | sha only | Crew: checkpoint, push approved after history rewrite |

Full ids:

| original | final |
|---|---|
| `f5f271faafbf86a0c5476528384ee00539d01c48` | `f5f271faafbf86a0c5476528384ee00539d01c48` |
| `de1fc73e80a7557f53ef8b77da2675ec06e2b70f` | `de1fc73e80a7557f53ef8b77da2675ec06e2b70f` |
| `2edb78bfdc2ec7328ed3c78a8b4463a71916a1bc` | `2edb78bfdc2ec7328ed3c78a8b4463a71916a1bc` |
| `a9ac612ae0c037c34481f3d33d5757c515d05253` | `a9ac612ae0c037c34481f3d33d5757c515d05253` |
| `2522755f784c8fa9d0bc3683aef60b9d0dc51c7f` | `2522755f784c8fa9d0bc3683aef60b9d0dc51c7f` |
| `c51b331e5ba7c099e075ec00fc9f66df74fa632e` | `c51b331e5ba7c099e075ec00fc9f66df74fa632e` |
| `e3502e5290d75611a2e30b541b846632c6486868` | `e3502e5290d75611a2e30b541b846632c6486868` |
| `e65d1a9c7abb39338222066a15224e20b9889444` | `e65d1a9c7abb39338222066a15224e20b9889444` |
| `5a851dda2eaa16d02560689524bb17ee309e6bea` | `5a851dda2eaa16d02560689524bb17ee309e6bea` |
| `45eafdf39479ebecb0977e9b6e0d6f60122c2787` | `45eafdf39479ebecb0977e9b6e0d6f60122c2787` |
| `2b9e1fe3aa8b9e6c36da633f5a5af3b10af2a919` | `2b9e1fe3aa8b9e6c36da633f5a5af3b10af2a919` |
| `d9ba0161a1234238c1fd9cba03116012afce03fe` | `d9ba0161a1234238c1fd9cba03116012afce03fe` |
| `aed1a5c417334010ee87ee34dc40a2b5e56769e6` | `aed1a5c417334010ee87ee34dc40a2b5e56769e6` |
| `19a96a424171a42978c4ebdfd95b55d0bdfe82ac` | `19a96a424171a42978c4ebdfd95b55d0bdfe82ac` |
| `908dd0cae175c5b357ae2bee451e02ba09c53036` | `908dd0cae175c5b357ae2bee451e02ba09c53036` |
| `8129eca77e71ea712c20c124e7a75bad4b32bac8` | `8129eca77e71ea712c20c124e7a75bad4b32bac8` |
| `8900748f47ca3806f3c93a4bc35fbdeec514a2dd` | `8900748f47ca3806f3c93a4bc35fbdeec514a2dd` |
| `70dc3b2bb895580c7bf050f19598cca7965b89dc` | `63b6d6b05a6840fd2ff59cf0780b2a56aa43eb29` |
| `51b411e425ee88e395f720f7d05aab7549a6d344` | `9a26bc2a24f4cd9733ec64ffaa2e2370b7bb21a0` |
| `94a3ec9c7d8371abaea0bef5e69fcf1fb9c17316` | `72101ec9eca029ebbea08e8b91a11696e373c10d` |
| `9a891c9c1142e7382fcd791ecc2f033d66f8c7a3` | `523867e6345187d42835f135ef4e37f5555d2c1d` |
| `f73c1cc6b879d78b1574445852fed31697921c15` | `54ed3c63f1b38d48059b9368eeff05a86332bd0e` |
| `4a08c489468e76a7cfb5202a86a0bd3b458d7db2` | `39a8fbb039098ca62d690bae319cc74318aa3b1d` |
| `8f57af964b489f5ab4a09780d96c5af71df6553c` | `7d357b8088ba1a6d1c9db6a095bbd1394088286e` |
| `843d22345aea57a92c8b41ea101be449ba17a541` | `1ce54c40e8314cbf499b3b8bcc6c8ea7c9c67469` |
| `f5f9bef4e5d7cb54bb517b9c76016fe7c95ee6ba` | `a6883ba3f4525da974a8431a73476e2d5d31a806` |
| `eba060a95f89fdbddec5458bd38b1dd0f4e0b670` | `add4ba2305771ae7d144caad55ae0e10c95ffbef` |
| `ee74d05f34e0c5d525cebe1dbeb1ff18b85059f3` | `f14e31c839b01a1378b2af982e4c4a550af0ac85` |
| `ba367cccf76c0b84861f6b3916708ba322e6cc2a` | `3ebc9cff67a846ffdcd24545f4af3c20ff4d0109` |
| `8f8fc7ae8e71b7205b8a7687f2639ab9024059b8` | `8be3000199c410a63eeebca832e4f4f18e367730` |
| `b54cc182d599259f79a0cb2d5e3f23880df10f24` | `6176e2fdc895d8d3cf795dc23b13afec1b07799e` |
| `6d75b88ccf6c0e0619665ba27b1f3b0c3ea9ec0b` | `78434d202fa08561638dfd6a3e03ed7f6b46b6cd` |
| `0424e9c7d957a9a360b54dd97741cbb861865016` | `cc05d17bbedc3d9c7bedc734839452f5c567b4bd` |
| `47890a629cc6ea91029bcb34b6f0238a830e47a5` | `1bfdb4f430aa424f9f521cc9027de60d6e68a9f2` |
| `97b653d0e792074884e1be5f9386e0625855a71e` | `610fa456e5fc3888f06d436caca4c006fdf33eb6` |
| `8b84914bc04482a1c07875c6ccafe00df2ab72fc` | `10e75542a29035b98f60f0384148de0fee11a671` |
| `638dc3acb9bac8ca21d47ddc7295a81b4547a769` | `0c10e9153ed6e94a715619f39bb2d63acb7bcb52` |
| `fc22f41baae66f9f7a869bf9ac1dd77dfeacd92d` | `e144a50d832cc307df8af6896918fce8f84d2a63` |
| `e8048ed17d866b78f25688ae359c52feae15a991` | `b5b558ecf99f9dfb0b792f4163987ee5e5dc8626` |
| `4c8169142d084c8726ab0e8e240eb6de9158116a` | `e240a02b5a95c7c998fbab93c19301522a4bfef2` |
| `d52149ae347fa926d25acabf97edd93103a32430` | `4ce6bd15374cd66f8a816aa034c02b89473d100a` |
| `ba55025e411e3b0e0493004ca6d2be4991d45268` | `78aff917fc1894c7eabc555d40a11467984c7b16` |
| `f4bfeaa5d4c6b339e74491ef8f221bdda25d367d` | `9148930b475ce5acabfb52c4fcccd37d521a33d2` |
| `57643ca895ac91750ec8c11c6c2ead1ef110567d` | `612778f2ff429559cefbc8edccf0c481c27d77c2` |
| `7bd6ab94f14bcdcb63a622cdf3c71855e0e6bdbe` | `91228752283a5cf237141bca95b54035a0039c11` |
| `12eb48099418d1b6e8b3e44047fe903b8c6726b8` | `5ebafae19626b1200e9f77f84c1e8801d0936d0e` |
| `5713ed5d3c8bd70f8d6750943315c0d40f871067` | `a01a7e5aa1f5e2ebdfd5007d4406c5a1ccdad70d` |
| `b7f4ac07de944927d51fb48376e0aaf775b9d096` | `1f530b24ead98a84a10ef179bb0452bdbd5177d9` |
| `536b3ecac830ef898e9c6dcb2dfc2d12c2079f94` | `c51f9b3d5184a02020174e95880dd875ec444a09` |
| `b7eaab517a516d997ea50296864d2a9b5bbf4352` | `7cb3d84438d55b1c6798c7625cc1e019de5c17d0` |
| `936337d1342222f28fb25b778bee17f96332ca78` | `3a21f8a0da04a1e847ce372839e86ee8806afb8d` |
| `bd5a557bf2f26bd48d7a6f2031bac5fef0fba955` | `7b6498df9d86bffcaf60b541fba4f43e8cd6547a` |
| `39d25068d0febd81060043373a9be7784ac9beb9` | `fbb232360515456b5c49d5d2d3902cded8e322a3` |
| `c7066f09fefe4e220800bddb2eb35cf1d50c5063` | `db18769674e2b04414a6ede263e8970174055038` |
| `263926ae5ded7cc1b8ed6c66a09d2f45938cfc21` | `44c71686190e59e1535c34066e11c640cc52d075` |
| `9778ce8268b9ba5a4cda304f70980f96dbdbf394` | `b0118ab69f379d3b0a734f6bffc83a6e5944dad1` |
| `ae9add3d56ba248b89a3cdaa46f4776156843058` | `5769469e8991f27ae7234d03cfca47790dd97834` |
| `d4a50d6ce05d64d428e6679b32989c25d6b2544d` | `3ba777e557aabe1a35b04dc2da3ee737921049ee` |
| `869effcba1415a85d5e7b55ecf08381c4095c5cb` | `5404700ba189f7625e9577561b20141484357e65` |
| `dafa06262b368270314ac874d249954dc8d7d71b` | `3685f5896b7acfdd22cf682120b32f7278aeefaf` |
| `1e1e90af364cec8a559d29aa8ee2982b70e775a1` | `da0f2eb73593b6ac54ad618f985f1f6a64e84f5a` |
| `43402f76fa447197d7a7cfa1d23bad88c51594b4` | `7811bce7dabf265143eb59236fe9a2a47f926d46` |
| `c0b7886aeaae7447b9572e23c3e11d09c7dfef0f` | `62d459723bbf1a5efa8f9f6528c0e2eba4e3b1ac` |
| `1b496d264a5eadeab02f3fbccb5375c9b68ea948` | `3fca81905be755829b0937ea83c00eaf090d9007` |
| `d520ff7c0fc7fca8da7f6337107fe8816c62464b` | `dbd549f2c74f58edd862e60334c6ba33f33e8c97` |
| `5b504b78f2ead4f760782c23a68d2a97d94db7e3` | `7e58784550a0797b76a986fe6bb9fdf126cb7f92` |
| `9976d3b8fe87d969542ab7602877f149753615d0` | `2dce7755f91abe0d73896885de594231be71f727` |
| `007b8b2366dcba00747ad027163c544f9a305441` | `ec1ac97cbf4fe3785a5e968450db3989a2bcd9eb` |
| `df7fdc1203a99d08d4c9b1e8edfe4db8c3192af2` | `0f3539b3cd7275ed4b6540075f93ba3740301a14` |
| `6d46ecbefb46de79f9da78ded86c5014a8a27cc8` | `bee0c434bf67faace2c55c060d616aadb2b3d335` |
| `de6ee5e477d1ead1219be01220dea9a29c650016` | `2405965583fc24f68f238d9dd9f71795781b64e2` |
| `6b4939b6bf5461130d2adcb689a5bcfe2809af19` | `f86edd3cb974a09e86bb6d284446f0329e9fe869` |
| `9b1e7a3f4f65f9a761a5828d2adb991dd22d5b0b` | `e039d97227f7ac0c811a76a45dca0ffbde8ea092` |
| `b9dec8379a2a2ae79d81dfb3aad532b76d861ae8` | `4da375547d84409aa16bd82b5631162d6a77b126` |
| `8a8190752469484dd869cd18eefcd70885aad179` | `04360ec6a44bb6aaa2222cc605ab3979718be50a` |
| `07b7d1a143e85e7a4a07090a7a4f6a570a2c4740` | `776b5c685afc2c072748285df9210c2643420ffa` |
| `ee1daa3ce94107b1ec9105afe9e5e70ebba9159c` | `b8c4838f84f99d78837becd58fe3d744fe147553` |
| `2307db22628c1d7c91e33be986b854f54b5dedf0` | `0c674c98b4284e586455c7f8dfaa93c736bbd690` |
| `131c3a1658183452eb7a676652869facc37fb891` | `a2e8c0c2fb8145dfdedbf8fad33f3820d96e7309` |
| `4cedbd17509ea4b89d1c2d16571e2fe68d433bea` | `63ad237634e3d046b78d14a7f554795808d3c316` |
| `8120b8aa4b1cee289d3c9305e8e72b3fd368ac77` | `1107616fc85fdd1294485c3cc50b0094f0a39457` |
| `138569239e656e3a10d8fb7378dff36d84ba1b13` | `d76b730bb5cae5b6d4a470f02a6d37bfa98127a9` |
