import json

import numpy as np

from sim.datagen.generate import generate


def test_same_seed_same_data(tmp_path):
    a = generate(tmp_path / "a", seed=3, n_equip=8)
    b = generate(tmp_path / "b", seed=3, n_equip=8)
    assert a == b
    assert (tmp_path / "a" / "points.csv").read_bytes() == (tmp_path / "b" / "points.csv").read_bytes()


def test_answer_key_matches_injected_anomalies(tmp_path):
    key = generate(tmp_path, seed=5, n_equip=40)
    import sqlite3

    con = sqlite3.connect(tmp_path / "legacylab.db")
    for c in key["charts"]:
        x = np.array([v for (v,) in con.execute(
            "SELECT value FROM points WHERE chart_id=? ORDER BY idx", (c["chart_id"],))])
        if c["anomaly"] == "shift":
            cp = c["change_point"]
            assert x[cp:].mean() - x[:cp].mean() > 0.8 * c["sigma"]
        if c["anomaly"] == "outlier":
            for i in c["outlier_idx"]:
                assert abs(x[i] - c["mean"]) > 4 * c["sigma"]
        if c["data_kind"] == "count":
            assert np.all(x >= 0) and np.all(x == np.round(x))
        assert c["anomalous"] == (c["anomaly"] != "normal")


def test_ocr_trap_ids(tmp_path):
    generate(tmp_path, seed=1, n_equip=40, trap_ratio=1.0)
    eq = (tmp_path / "equipment.csv").read_text(encoding="utf-8-sig")
    assert "Å" in eq or "O0" in eq or "I1" in eq
    json.loads((tmp_path / "answer_key.json").read_text(encoding="utf-8"))
