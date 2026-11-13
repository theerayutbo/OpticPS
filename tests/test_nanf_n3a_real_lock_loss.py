"""Gate N3 part a, review 4 observation 4: a real lock loss on the pinned chain, no stubbed RLS.

Synthetic data only. No workbook is read, no fit is run, nothing is frozen. One full-size run at a
received power far below the sensitivity of the 80 Gb/s link (about 20 s).
"""

import numpy as np

from opticps.measurement import nanf_chain as nc

NOISE_LIMITED_ROP_DBM = -30.0


def test_the_real_equaliser_loses_lock_on_the_pinned_chain_and_the_run_is_marked_invalid():
    outcome = nc.run_point("80G/B2B/-30.0", nc.TxRxParameters(), 80, NOISE_LIMITED_ROP_DBM)
    assert outcome.lost and outcome.result is None  # nothing stubbed: the pinned RLS ran
    assert outcome.reason.startswith("trace cap acted") or outcome.reason.startswith(
        "RlsInstabilityError"
    )
    assert nc.lost_report([outcome]) == [f"LOST LOCK 80G/B2B/-30.0 at -30 dBm: {outcome.reason}"]
    arrays = nc.curve_arrays([outcome], calibration=True)  # a lost point needs no declared point
    assert arrays.valid.tolist() == [False] and arrays.n_lost == 1
    assert np.isnan(arrays.ber).all() and np.isnan(arrays.snr_db).all()
