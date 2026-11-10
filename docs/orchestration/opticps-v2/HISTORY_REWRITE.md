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

- Serial: `docs/benchmarks/MISSING_PARAMETERS.md`, line 110 of the versions in `12eb480` -> `f9d8a2d`, `5713ed5` -> `802e95f`, `b7f4ac0` -> `539bae0`.
- Article text: `configs/benchmarks/ran_2025_g652d.yaml`, `docs/benchmarks/SOURCE_REGISTER.md` and
  `tests/test_benchmark_provenance.py`, in `70dc3b2` -> `63b6d6b`, `51b411e` -> `9a26bc2`, `94a3ec9` -> `72101ec`, `9a891c9` -> `523867e`, `f73c1cc` -> `54ed3c6`, `4a08c48` -> `39a8fbb`, `8f57af9` -> `7d357b8`, `843d223` -> `1ce54c4`, `f5f9bef` -> `9e49ff1`, `eba060a` -> `818a661`, `ee74d05` -> `cd5622a`, `ba367cc` -> `c2e2a9c`, `8f8fc7a` -> `802e1a1`, `b54cc18` -> `019bdd8`, `6d75b88` -> `ba02fc9`, `0424e9c` -> `db67292`, `47890a6` -> `d3b1b5d`, `97b653d` -> `74a9317`.

## Second step: author and committer address

Seven commits carried an author or committer email made of the local user name and the local hostname. A second
`git-filter-repo --mailmap` run (branch only, `main` untouched) mapped that address to the noreply address used on `main`
and on the other 75 branch commits, keeping the name. The tables below map each ORIGINAL pre-rewrite id to its FINAL id
after both steps. After the step, all 164 author and committer fields above `main` use the noreply address.

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
| `f5f9bef` | `9e49ff1` | content | E0 fix: typed constructors, strict loader, untypeable VERIFIED, leakage on all identities, |
| `eba060a` | `818a661` | content | E0 fix: handoff, fix round and mutant list |
| `ee74d05` | `cd5622a` | content | N0 fix: corrected NANF sources record, content-based third-party guard, fix-round handoff  |
| `ba367cc` | `c2e2a9c` | content | Crew: record N0 gate and E0 reviews |
| `8f8fc7a` | `802e1a1` | content | N1 step 1: plan Amendment 2 (C1 cases, C5 range, A2 d vs own no-fibre, B2B gate, A1.7 rang |
| `b54cc18` | `019bdd8` | content | N1: NANF fibre profiles with provenance, profile-driven coherent propagation, configs, tes |
| `6d75b88` | `ba02fc9` | content | N1 fix round: slope path from reference wavelength, scenario minima and label, loader stri |
| `0424e9c` | `db67292` | content | E0 fix round 2: byte-compared freeze guard with history check, plan Revision 2, licence an |
| `47890a6` | `d3b1b5d` | content | E0 fix round 2: handoff |
| `97b653d` | `74a9317` | content | N1 fix round 2: D anchored at its stated wavelength for every S source, wavelength-bound r |
| `8b84914` | `328a9a0` | sha only | E0 fix round 3: narrowed freeze-guard promise, fixed criterion path, whole-criterion signa |
| `638dc3a` | `ab37e90` | sha only | Crew: record N1 gate and E0 third review |
| `fc22f41` | `d447c1b` | sha only | E0 fix round 3: status record with final pin and counts, pending review |
| `e8048ed` | `6df9b88` | sha only | N2a: close N1 minors (boolean slope gate, scenario S never overrides a table, scenario D s |
| `4c81691` | `1e1d22c` | sha only | N2a: mutation script, match the formatted slope guard (28 of 28 killed) |
| `d52149a` | `665e3bc` | sha only | E0 fix round 4: full-history merge routes, symlink refusal, plan Revision 4, known-limits  |
| `ba55025` | `7771eeb` | sha only | N2: stdlib NANF workbook importer (SHA-256, default-deny schema, holdout withheld), Fig.1  |
| `f4bfeaa` | `3627f54` | sha only | Crew: record E0 closing reviews |
| `57643ca` | `d3e1a6d` | sha only | E1a: plan Revision 5 (retraction corrected, new pin), local hashes verified, known limits  |
| `7bd6ab9` | `0709f16` | sha only | N2 fix round: withdraw false >60 GHz mismatch, per-wavelength loss bound, measured evidenc |
| `12eb480` | `f9d8a2d` | content | E1: read-only external capture reader, B2B format verification, fractional-sps timing, str |
| `5713ed5` | `802e95f` | content | Crew: record N2 first-part gate |
| `b7f4ac0` | `539bae0` | content | N3 step 1: plan Amendment 5, N2 leftovers closed, QA5 survivors killed |
| `536b3ec` | `3d5c9ee` | sha only | E1 fix round: one holdout gate for every route, physical pass apart from structure, plan R |
| `b7eaab5` | `694d4b3` | sha only | N3a: RLS DFE, NANF simulation chain, C1-C8 scoring, identifiability, freeze-gated holdout  |
| `936337d` | `d3bfee2` | sha only | E1 second fix round: CLI routes gated by a walked list, whole-record block pass, plan Revi |
| `bd5a557` | `005bff0` | sha only | E1 second fix round: tests for the clipping, distinct-value and changed-file guards, mutan |
| `39d2506` | `7d0799e` | sha only | N3a fix round: plan Amendment 6, trace cap pinned at 1e10, default deny, freeze binds a co |
| `c7066f0` | `c03c50e` | sha only | N3a fix round: mutant script runs the fast test files first |
| `263926a` | `edbb4ed` | sha only | N3a fix round: tests for seven surviving freeze guards, four equivalent mutants removed fr |
| `9778ce8` | `c8cf6a1` | sha only | E1 third fix round: route claim narrowed to typed CLI options, plan Revision 8, block pass |
| `ae9add3` | `22713f6` | sha only | E1 third fix round: test that a change before the pass is refused before any block is read |
| `d4a50d6` | `60dd057` | sha only | N3a: plan Amendment 7, lost-lock runs are invalid, reported, and never help a score |
| `869effc` | `c56745c` | sha only | N3a Amendment 7: tests for two surviving mutants (all points lost reason, infinite evaluat |
| `dafa062` | `c3a431f` | sha only | N3a: Fix round handoff with the Amendment 7 summary and final gate counts |
| `1e1e90a` | `58ea212` | sha only | E1 closing round: require_frozen_criterion stated as an E2 obligation, shrinking-file word |
| `43402f7` | `fe24842` | sha only | Crew: record Gate E1 reviews and PASS |
| `c0b7886` | `6b85aec` | sha only | E2a: scoring entry point, frozen estimators, B2B surrogate, B2B-only model and pre-registe |
| `1b496d2` | `821bd2d` | sha only | E2a: plan Revision 10, scoring entry point, model, frozen criterion definition, code ident |
| `d520ff7` | `939bab7` | sha only | E2a: freeze the TERIPHIC criterion (plan Revision 10) |
| `5b504b7` | `0b9a7e5` | sha only | E2a fix: bind the freeze to its inputs, selected scenario added once, new criterion path |
| `9976d3b` | `8eec6e2` | sha only | E2a: plan Revision 11, freeze bound to its inputs, first freeze superseded |
| `007b8b2` | `86f3b36` | sha only | E2a: freeze the TERIPHIC criterion at the R11 path (plan Revision 11) |
| `df7fdc1` | `512c44a` | sha only | E2a: Dev handoff |
| `6d46ecb` | `ba54db8` | sha only | N3a second review: plan Amendment 8, holdout record corrected, Fig.11 excluded, guards clo |
| `de6ee5e` | `40595d3` | sha only | N3a second review: ascending-eigenvalue test, one equivalent mutant removed from the list |
| `6b4939b` | `488ad20` | sha only | N3a second review: Fix round handoff with the Amendment 8 summary and final counts |
| `9b1e7a3` | `5111ff7` | sha only | E2a fix round (review FAIL at 2c0bf34): governance fixes, gain-invariant two-stage criteri |
| `b9dec83` | `7eb623a` | sha only | E2a: plan Revision 12 (R11 reviewed, failed and never scored), review E2a_qa.md |
| `8a81907` | `79467d8` | sha only | E2a: freeze the TERIPHIC criterion at the R12 path (plan Revision 12) |
| `07b7d1a` | `734193d` | sha only | E2a: Dev handoff after the fix round |
| `ee1daa3` | `69df2fa` | sha only | E2a: tests for a register MD5 mismatch alone (mutant md5_not_required), before and after t |
| `2307db2` | `12c2f48` | sha only | N3a closing review: plan Amendment 9, calibration flag checked, grafts from the common dir |
| `131c3a1` | `c679cef` | sha only | N3a closing review: tests for two surviving calibration-path mutants |
| `4cedbd1` | `25e8b7c` | sha only | E2a: tests for the survivors of the end-to-end mutant run (pin format, first-parent line,  |
| `8120b8a` | `89300ce` | sha only | Crew: pause checkpoint; record N3a reviews 1-3 and E2a state |
| `1385692` | `030e6ae` | sha only | Crew: checkpoint, push approved after history rewrite |

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
| `f5f9bef4e5d7cb54bb517b9c76016fe7c95ee6ba` | `9e49ff14a5d7eed727effa5b147ca10a52b82bf7` |
| `eba060a95f89fdbddec5458bd38b1dd0f4e0b670` | `818a661af3d16fca3a7bf467f0d27f9c9f969760` |
| `ee74d05f34e0c5d525cebe1dbeb1ff18b85059f3` | `cd5622aab5de52ea6fc02e614d619edf3e650338` |
| `ba367cccf76c0b84861f6b3916708ba322e6cc2a` | `c2e2a9ce4644ed9eab8c8da84dcd83aa30e6a320` |
| `8f8fc7ae8e71b7205b8a7687f2639ab9024059b8` | `802e1a1167848d8154047908267f16afc5b43a35` |
| `b54cc182d599259f79a0cb2d5e3f23880df10f24` | `019bdd8f877138da6e620894d921767f82cbac5f` |
| `6d75b88ccf6c0e0619665ba27b1f3b0c3ea9ec0b` | `ba02fc9e119a548538829e2c7c7ab54081d455a5` |
| `0424e9c7d957a9a360b54dd97741cbb861865016` | `db67292068293ca084f5cdaaa6469058dfd2ca92` |
| `47890a629cc6ea91029bcb34b6f0238a830e47a5` | `d3b1b5daae12a25f8783003d1f9f182b6ea9fd6a` |
| `97b653d0e792074884e1be5f9386e0625855a71e` | `74a931790435adb2221ea05fb9304919e0bb77a8` |
| `8b84914bc04482a1c07875c6ccafe00df2ab72fc` | `328a9a0e5ce5d6a818379d30637fba75025ddea7` |
| `638dc3acb9bac8ca21d47ddc7295a81b4547a769` | `ab37e9050207d2ac5b72c814b4afac8fca06f586` |
| `fc22f41baae66f9f7a869bf9ac1dd77dfeacd92d` | `d447c1b6d0b899a6cdc4669c8cd68507414f1a61` |
| `e8048ed17d866b78f25688ae359c52feae15a991` | `6df9b88538c0b7da9dfe61a5e5401dc82b169d86` |
| `4c8169142d084c8726ab0e8e240eb6de9158116a` | `1e1d22cf6b1eb05e11bcceb909f95fcd5dda5f18` |
| `d52149ae347fa926d25acabf97edd93103a32430` | `665e3bcb79fd62e6ba8d771cd0c6367be52b9936` |
| `ba55025e411e3b0e0493004ca6d2be4991d45268` | `7771eeb6db4a018cd50d0bab0a8bbe49e0cd0caf` |
| `f4bfeaa5d4c6b339e74491ef8f221bdda25d367d` | `3627f54b555b8440f6da3c973febdc31da20cb79` |
| `57643ca895ac91750ec8c11c6c2ead1ef110567d` | `d3e1a6dd719a726164a2fb1439d809c5a7da2544` |
| `7bd6ab94f14bcdcb63a622cdf3c71855e0e6bdbe` | `0709f16369bc21a4962d16f7357dd24e73b76e32` |
| `12eb48099418d1b6e8b3e44047fe903b8c6726b8` | `f9d8a2db77650e75c9d52821f61e7bee49899ae7` |
| `5713ed5d3c8bd70f8d6750943315c0d40f871067` | `802e95f78e0e90c6476fe3024fe7431c4f474b10` |
| `b7f4ac07de944927d51fb48376e0aaf775b9d096` | `539bae006b0ec13e16d3e344c6b437c0d50386a3` |
| `536b3ecac830ef898e9c6dcb2dfc2d12c2079f94` | `3d5c9ee5e7c0378c86b9fb7ed39fd73da272d017` |
| `b7eaab517a516d997ea50296864d2a9b5bbf4352` | `694d4b3c89470f59dc4a01aaf12f401bff7b1784` |
| `936337d1342222f28fb25b778bee17f96332ca78` | `d3bfee286e9ea13592e8e972f9dab041aa0bae38` |
| `bd5a557bf2f26bd48d7a6f2031bac5fef0fba955` | `005bff0b72c8adfca4f1b15449cef9f7da721309` |
| `39d25068d0febd81060043373a9be7784ac9beb9` | `7d0799e52885b96b5d4499c3250d6a4d0db25df6` |
| `c7066f09fefe4e220800bddb2eb35cf1d50c5063` | `c03c50e347eff2a6b954106acead585ddb76a471` |
| `263926ae5ded7cc1b8ed6c66a09d2f45938cfc21` | `edbb4edf70cad8fbba33009356744b3b23a46c0f` |
| `9778ce8268b9ba5a4cda304f70980f96dbdbf394` | `c8cf6a1d189a8b146d991e41da386d149937f4f6` |
| `ae9add3d56ba248b89a3cdaa46f4776156843058` | `22713f64562d8db307be69dbe95d49a13c16028a` |
| `d4a50d6ce05d64d428e6679b32989c25d6b2544d` | `60dd057ebdbe3be9d6aa8df06f6922327ca6bfc7` |
| `869effcba1415a85d5e7b55ecf08381c4095c5cb` | `c56745c71bd6470d7efd0be1cd13289a440d6459` |
| `dafa06262b368270314ac874d249954dc8d7d71b` | `c3a431fe31e1b62ade919bd1ce26332301bb2ebc` |
| `1e1e90af364cec8a559d29aa8ee2982b70e775a1` | `58ea21282e6e596ae555877e520123354ca026d3` |
| `43402f76fa447197d7a7cfa1d23bad88c51594b4` | `fe24842d2df02ab7a518bb860497cc9e864741fe` |
| `c0b7886aeaae7447b9572e23c3e11d09c7dfef0f` | `6b85aec48857d3514b9cff05d1daf57bbfcf46b7` |
| `1b496d264a5eadeab02f3fbccb5375c9b68ea948` | `821bd2d6991b34be12de1ee38b09005619bcbfd0` |
| `d520ff7c0fc7fca8da7f6337107fe8816c62464b` | `939bab77436b3b5555e836e924e1051cc523d162` |
| `5b504b78f2ead4f760782c23a68d2a97d94db7e3` | `0b9a7e5c7ecd0fa46bde90633412cc87b40bdba9` |
| `9976d3b8fe87d969542ab7602877f149753615d0` | `8eec6e246a711e5c64e5bf02176104563b754b4e` |
| `007b8b2366dcba00747ad027163c544f9a305441` | `86f3b365b3d50ad407f83ba5189e840da61efa2d` |
| `df7fdc1203a99d08d4c9b1e8edfe4db8c3192af2` | `512c44ae48e5db573eff9780677c99d82a5a26c1` |
| `6d46ecbefb46de79f9da78ded86c5014a8a27cc8` | `ba54db88ff393fcef1378e9d6ca7fcce712d5e83` |
| `de6ee5e477d1ead1219be01220dea9a29c650016` | `40595d32d6af1cab496bfa347f3f6071d2ca8b37` |
| `6b4939b6bf5461130d2adcb689a5bcfe2809af19` | `488ad20e3a25cfec61bfd840ea53704c56f6530f` |
| `9b1e7a3f4f65f9a761a5828d2adb991dd22d5b0b` | `5111ff768b56f1dee5f2890a9b0e7aff9a9ee79f` |
| `b9dec8379a2a2ae79d81dfb3aad532b76d861ae8` | `7eb623aa66519c3e6ebd3930e67923f860d4ab93` |
| `8a8190752469484dd869cd18eefcd70885aad179` | `79467d8e289c9e6f91c94f2a503a5c92a834e78a` |
| `07b7d1a143e85e7a4a07090a7a4f6a570a2c4740` | `734193d59bb1d96591717d4de9ea33987468baed` |
| `ee1daa3ce94107b1ec9105afe9e5e70ebba9159c` | `69df2fa78a6603f2f038a1ced7dc55f2e9265da5` |
| `2307db22628c1d7c91e33be986b854f54b5dedf0` | `12c2f480907afcff1a1164900f2b1368a0020af0` |
| `131c3a1658183452eb7a676652869facc37fb891` | `c679cef1da187b9e97a7badbe328da82b76261fb` |
| `4cedbd17509ea4b89d1c2d16571e2fe68d433bea` | `25e8b7c26ed1e35483736e9362802f15545dd54c` |
| `8120b8aa4b1cee289d3c9305e8e72b3fd368ac77` | `89300ceac7f9cf8a07875752b4f2b9fd3a2fa088` |
| `138569239e656e3a10d8fb7378dff36d84ba1b13` | `030e6aeb7f607efcb2dc4f8b6a656eb6a657df33` |
