# OpticPS Roadmap v2: แผนดำเนินงานที่สรุปร่วมกับ Fable

## Context
เจ้าของโปรเจกต์ตัดสินใจขยาย OpticPS v1.2 (PAM4, จำลองล้วน, ไม่มีข้อมูลแล็บ) เป็น adaptive M-PAM ตาม `OpticPS_Claude_Code_Roadmap_v2.md` ซึ่งแทนฉบับเดิม เป้าหมายคือความถูกต้องทางวิทยาศาสตร์และการทำซ้ำได้ ไม่ใช่จำนวนฟีเจอร์ แผนนี้มาจาก gap audit (Explore) และการวางแผนของ Fable ผมตรวจเลขสำคัญซ้ำแล้ว: PAM2 ที่ 12 dB, ความยาว head, H288/H272, Protocol B และ ENOB 5

สถานะฐาน: HEAD `a2eb969` บน `main`, CI เขียว, pytest ผ่านทั้งหมดในเครื่อง (จำนวนแน่นอนจะบันทึกใน Gate 0), ruff check และ mypy ผ่าน, มี 244 test functions ก่อน parametrize ไฟล์ roadmap ทั้งสองยัง untracked

## กติกาตลอดงาน
- Clean room ตาม §B: ไม่แตะ OptiCommPy หรือ simulator อื่น ไม่ว่าทางใด และไม่สั่ง subagent ให้ทำ
- ทำบน branch ใหม่ `v1.3-mpam` commit ในเครื่องเท่านั้น ไม่ push, merge, tag, release และไม่แตะเครื่องมือจริง
- ไม่แก้ waveform, checksum หรือ results ที่ commit แล้ว และไม่แก้ golden เพื่อให้เทสต์ผ่าน
- ไฟล์ roadmap ไม่ commit (เป็นของเจ้าของ) บันทึก SHA-256 ไว้ใน `docs/ROADMAP_STATUS.md` แทน
- ทำงานแบบ Crew: Dev = Sonnet, Loki = Opus, ไม่ใช้ Fable เป็น worker แต่ละ commit ต้องผ่าน targeted tests, pytest เต็ม, `ruff check`, `ruff format --check`, mypy, byte anchor และ Opus PASS
- ถ้า `ruff format --check` ไม่ผ่านอยู่แล้วที่ baseline จะบันทึกเป็นปัญหาเดิม และจัดการใน commit แยก เฉพาะถ้าไม่เปลี่ยนพฤติกรรม

## Gate 0 (C1)
- สร้าง branch, `docs/ROADMAP_STATUS.md`, `docs/FEATURE_GAP_MATRIX.md` (EXISTS/PARTIAL/MISSING/BLOCKED พร้อม file:line)
- ใช้ `scripts/license_audit.py` และ `docs/sbom.cdx.json` ที่มีอยู่ อัปเดตจาก lockfile และเพิ่ม `docs/DEPENDENCY_EXCEPTIONS.md`
- แก้ `docs/CLEAN_ROOM_DECLARATION.md` ให้ตรงความจริง: แยกกระบวนการพัฒนา OpticPS ออกจากการที่ ChatGPT/ผู้รีวิวเคยเห็นบางส่วนของ OptiCommPy, ระบุว่า AI ไม่สามารถรับรองการไม่ได้รับอิทธิพลทางอ้อมจากข้อมูลฝึก, ไม่ใช่คำรับรองทางกฎหมาย
- **Byte anchor** `tests/test_pam4_anchor.py` (marker `slow`): regenerate ทั้งสองโปรไฟล์ด้วย `configs/m8199b_profiles.yaml` เดิมลงโฟลเดอร์ชั่วคราว เทียบ SHA-256 กับ `checksums.sha256` สำหรับ waveform, symbols, info bits และ `experiment_manifest.csv`; เทียบ `*_metadata.json` โดยตัด key `generator`; เทียบ `adaptive_selection.json` ที่ rel 1e-12 ไฟล์ไหนไม่ตรงตั้งแต่ baseline ให้บันทึกเป็นปัญหาเดิมพร้อมสาเหตุ ก่อนเริ่ม Stage 1

## สถาปัตยกรรม Stage 1
- `ModulationSpec` frozen dataclass ใน `modulation/pam.py` และคง API เดิม ฟังก์ชันเดิมรับ `order: int = 4`; `Frame` เพิ่ม `order: int = 4` ท้ายสุด
- Config M-PAM อยู่ใน `configs/mpam_profiles.yaml` ใหม่ (`config_schema_version: 2`) เพราะ `experiment_id` ใช้ hash ของไฟล์ YAML เดิม ห้ามแก้ไฟล์เดิม
- ชื่อ PAM4 เดิมคงไว้ เพราะ payload RNG ใช้ crc32 ของชื่อ M≠4 ใช้ `PAM{M}_Uniform`, `PAM{M}_Fixed_Inner_H{centibits}`, `PAM{M}_Fixed_Outer_H{centibits}`, `PAM{M}_Adaptive`, `PAM{M}_BestFixed`
- Manifest: PAM4 คง 40 คอลัมน์เดิม M≠4 ใช้ schema v2 (`manifest_schema_version`, `modulation_order`, `bits_per_symbol`, `probabilities`, `realised_probabilities`, `shaping_family`, `shaping_parameter`, `entropy_target_bits`, `constraint_protocol`, `level_spacing_full_scale`, `head_symbols`) importer อ่านได้ทั้งสองแบบ
- `Selection` เพิ่ม `order, family, parameters`; `p_outer` ใช้เฉพาะ M=4; ฝั่ง consumer ย้ายไปใช้ `probabilities` พร้อม shim
- ป้าย evidence: `simulated|mock|measured|analytical`
- ใช้ชื่อ R_BMD ตามที่ repo คำนวณจริง ถ้าเขียน GMI ต้องระบุว่าหมายถึงอะไร

## คณิตศาสตร์ที่ตัดสินแล้ว
- **PSNR** บน unipolar levels i=0..M−1: `PSNR = (M−1)²/σ²`, `σ = (M−1)/10^(PSNR_dB/20)`; M=4 ได้ 9/σ² ตามเดิม PSNR เท่ากันข้าม M หมายถึง Vpp และ noise เท่ากัน รายงาน `E[x²]/σ²` แยกต่างหาก
- **Family:** per-pair `q_j = P(±x_j)`, `Σq_j = 1/2`; baseline MB หนึ่งพารามิเตอร์ และ `mb_for_entropy(H, order, sign)` เพราะ MB(λ) กับ MB(−λ) มี entropy เท่ากันเฉพาะ M=4
- **Quantisation:** `quantize_symmetric_composition` (quantise ครึ่งเดียวแล้ว mirror) เพราะตัวเดิมแยกคู่ได้เมื่อ M≥8 ต้องให้ผลเท่าของเดิมที่ M=4 ซึ่ง anchor พิสูจน์
- **Optimiser:** SMD เป็น concave บนเซต symmetric จึงอ้าง global ได้ เฉพาะ SMD ที่ไม่รวม matcher loss และสำหรับ channel ที่ fix ไว้ R_BMD ยังไม่พิสูจน์ว่า concave จึงใช้ multistart (uniform, MB ±λ ที่ 3 entropy, Dirichlet 4 จุดแบบมี seed) เก็บ log ทุกจุด และอ้างได้แค่ "best of N starts" Matcher loss เป็นขั้นบันได จึงประเมิน objective ที่ quantise แล้วซ้ำที่จุดจบทุกจุดก่อนเลือก
- **Rate bound:** `bmd_raw` ติดลบได้จริง เปิดเผยค่านี้และ clip อย่างชัดเจน ต่างจาก roadmap ที่เขียน `0 ≤ R` รวม ๆ
- **Constraints:** ที่ quadrature และ symmetric PMF ค่า mean optical power ไม่ขึ้นกับ PMF ดังนั้น `fixed_average_optical_power` เป็น `INACTIVE` และ `fixed_OMA` เท่ากับ `fixed_peak` เมื่อ bias และเลเซอร์คงที่ แสดงผลเป็น `INACTIVE` ไม่สร้างการเปรียบเทียบปลอม กรณีต่างกันจริงคือ off-quadrature, PMF อสมมาตร, หรือ outer levels ไม่ถูกใช้
- **Average-power ≠ inner-heavy MB:** ข้อจำกัดกำลังแสงเป็น first-moment ส่วน inner-heavy MB มาจาก E[x²] แบบ peak อิสระ ซึ่งต้องปรับ swing รายรูปคลื่น ห้ามทำเว้นแต่ประกาศล่วงหน้า Inner-heavy ชนะได้จากกลไกอื่น เช่น sine compression, clipping, noise ขึ้นกับระดับ โค้ดต้องอนุญาตผลนี้ ไม่ตั้งสมมติฐานล่วงหน้า

## ข้อมูลและ baseline
- ใน simulation "acquisition อิสระ" = noise realisation จากสตรีมไม่ซ้อนกัน (`SeedSequence.spawn`) ระบุชัดว่า payload เดียว
- `AcquisitionId(source, id, split, content_sha256)`; `assert_disjoint` ปฏิเสธทั้ง id ซ้ำและเนื้อหาซ้ำแม้ชื่อต่างกัน
- Best-fixed menu ประกาศใน config ก่อนรันผลทดสอบ: Uniform, Inner/Outer ที่ entropy deficit 0.12 และ 0.28 บิต (PAM4 คือ PS70, PS80, Outer70 เดิม; M=8 = H288/H272; M=16 = H388/H372)
- ค่า oracle ที่เลือกจาก test บันทึกเป็น `oracle_not_a_baseline` เท่านั้น

## Frame และ export
- Preamble 512 ใช้ outer indices {0, M−1}; head ต้องหาร 1024 ลงตัว
- Training: M=2,4 = 512 (เดิม), M=8 = 1536 (192 ต่อระดับ), M=16 = 2560 (160 ต่อระดับ; σ คลาดเคลื่อนราว ±5.6% ตามประมาณการ ต้องเทสต์ผลของ training ที่ยาวกว่า)
- Protocol A ใช้ 8/56 GBaud เดิม Protocol B nominal 112 Gb/s ที่ 224 GSa/s: sps 2/4/6/8 สำหรับ M=2/4/8/16
- Realised-rate equalisation ปรับ sample rate 200–256 GSa/s ที่ sps คงที่ (−10.7%/+14.3%) ระดับ PS80 ต้องปรับเกินนี้จึงรายงาน `INFEASIBLE`
- Export เป็น offline เท่านั้น เพิ่ม `dac_codes_per_level_step` เป็น diagnostic; ENOB simulation รอ Stage 2

## เทสต์อิสระ
ไฟล์ `tests/test_mpam_rates.py`, `test_mpam_frame_rx.py`, `test_constraints.py`, `test_leakage.py`, `test_cli_mpam.py`
- SER ปิดรูป `2(1−1/M)Q(1/(2σ))` ที่ M=2,8,16; PAM2 ที่ 12 dB = 0.0233 ใช้จับ PSNR ผิด factor
- Binary-AWGN ผ่าน `scipy.integrate.quad` ไม่ใช้ GH, |Δ|<1e-6; M=2 ได้ BMD=SMD ถึง 1e-12
- Embedding: PMF บน {0,M−1} เท่า PAM2; PAM4 บน PAM16 {0,5,10,15} เท่า PAM4 SMD ถึง 1e-9
- Trapezoid เทียบ GH 120 จุดที่ M=16 PSNR 8–30 dB, |Δ|<1e-6; GH 120 เทียบ 200 จุด <1e-9
- Bounds: 0≤SMD≤H≤log2M, BMD≤SMD; Gray: ที่ 26 dB อย่างน้อย 95% ของ symbol error พลิกหนึ่งบิต
- CCDM: enumerate ครบที่ alphabet 8, n=5; round-trip M=8/16, n=1024; ไม่แยกคู่; วัดเวลา (เกิน 1 s/block ให้หยุดทบทวน)
- Leakage: id ซ้ำ, hash ซ้ำ; CLI `generate → validate → simulate → report` M=4/8/16
- Negative: มีกรณีที่ shaping แพ้และ `INFEASIBLE` อย่างน้อยหนึ่งกรณี

## ลำดับ commit
| Commit | เนื้อหา | ขนาดประมาณ |
|---|---|---|
| C1 | Gate 0 + anchor | 300 บรรทัด |
| C2 | `rates.py` generic + เทสต์ rate | 250 |
| C3 | `distributions.py`, `ccdm.py`: pair family, entropy match, symmetric quantise, profiling | 250 |
| C4 | `adaptive.py`, optimiser, `optimization/constraints.py`, `AcquisitionId` | 400 |
| C5 | `ModulationSpec`, `frame.py`, `export.py`, `validate_export.py`, `mpam_profiles.yaml` | 500 |
| C6 | `dsp.py`, `capture_dsp.py`, block erasure และ info-bit BER แยกจาก label BER | 400 |
| C7 | `demo.py`, `uxr_ingest.py`, `compare.py`, `fiber_validation.py`, reports, CLI | 400 |
| C8 | Provenance, `docs/notes/mpam_rates_and_constraints.md`, CHANGELOG, README, status | เอกสาร |

ต่อจากนั้น
- **Stage 3:** S3-1 `ingest-uxr --diagnose` + `QualityGate` PASS/WARN/REJECT (ไม่ต้องมี sidecar, ไม่ให้คะแนน payload, ไม่เขียน registry); S3-2 `ExperimentPlan`, ลำดับ run แบบสุ่มมี seed, run sheet, `INFEASIBLE`, `POWER ANALYSIS NOT POSSIBLE`; S3-3 mock campaign พร้อม bad-data ของจริงยังคง `BLOCKED: REAL UXR EXPORT REQUIRED`
- **Stage 2:** S2-1 impairments default off (quantisation, ENOB noise จาก SINAD=6.02·ENOB+1.76, clipping, jitter, AC coupling; ปิดแล้วเท่าเดิม); S2-2 DFE เทียบ FFE บน high-ISI พร้อม guard; S2-3 soft LLR พร้อม prior (LLR hard decision = MAP, posterior รวมเป็น 1)

**จุดหยุดรอบนี้: จบ S2-3** แล้วรายงาน ลำดับคุณค่าทางวิทยาศาสตร์คือ 1 > 3 > 2 > 5 > 6 > 4 > 7 > 8 Stage 4, 5, 6 ทำต่อเมื่อเจ้าของสั่งรอบถัดไป เพื่อไม่ให้ Stage ที่พึ่งข้อมูลจริงกลายเป็นงานที่ดูเสร็จแต่พิสูจน์อะไรไม่ได้ สถานะตั้งต้น: Stage 4 `PARTIAL`/`BLOCKED`, Stage 5 ยังไม่เริ่ม, Stage 6 ยังไม่เริ่ม (ต้องเรียก `FEC-assisted shaped M-PAM` ไม่ใช่ PAS), Stage 7–8 ยังไม่เริ่ม

## ข้อสังเกตต่อ Roadmap v2 (เขียนลง ROADMAP_STATUS เป็น deviation)
- Stage 4 เป็น P0/P1 และ M5 พึ่ง M4 synthetic: นโยบายที่ตัดสินบนโมเดลของตัวเองพิสูจน์ได้แค่ความถูกต้องและการคิด overhead ไม่ใช่ประโยชน์
- M3 "พึ่ง M0 เท่านั้น" ไม่จริงสำหรับ intake ของ M-PAM ซึ่งต้องรอ C5/C6
- Latency budget ของ Stage 5 เป็นสมมติฐาน
- กฎ clean room ทำได้เฉพาะการไม่ค้นหรือเรียกคืนโดยเจตนา ไม่สามารถรับรองข้อมูลฝึกของโมเดล

## ความเสี่ยงและเงื่อนไขหยุด
ความเสี่ยงหลัก: float PAM4 เปลี่ยน, GH ไม่ลู่เข้าที่ M=16, CCDM ช้า, training PAM16 สั้น, อ้าง optimiser เกินจริง, schema แยกทาง, scope creep, seed 42 ใช้ร่วมหลายจุด (บันทึก stream key)

หยุดงานส่วนนั้นเมื่อ: anchor ไม่ตรงและอธิบายไม่ได้; invariant ข้อใดล้มเหลว; ต้องใช้โค้ดบุคคลที่สาม; Opus FAIL slice เดิมสองครั้ง; gain ใดไม่มี held-out interval

## การตรวจและรายงาน
COMPLETE ต้องจับคู่ทุกข้อใน exit gate กับเทสต์หรือไฟล์, มีจำนวนเทสต์ก่อนหลัง, anchor เขียว, lint/format/mypy ผ่าน, provenance, CHANGELOG, SHA และ Opus PASS ใน `docs/engineering_log/LOG.md` PARTIAL ต้องบอกข้อที่ขาด BLOCKED ต้องบอกข้อมูลจริงที่ขาด ทุกอย่างรอบนี้อยู่ไม่เกินขั้น 3 `SYNTHETIC END-TO-END VERIFIED` ของ claims ladder

รายงานสุดท้ายตาม J3: `Stage | Status | Implemented | Evidence | Missing/blocked | Next safe action`
