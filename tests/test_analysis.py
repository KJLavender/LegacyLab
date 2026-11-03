import numpy as np

from analysis import changepoint, spc
from bench.metrics import char_accuracy, detection_scores, row_exact


def test_imr_catches_outlier_and_baseline_scale():
    rng = np.random.default_rng(0)
    x = rng.normal(100, 1, 60)
    x[40] = 106
    d = spc.imr(x)
    assert d.anomalous and 40 in d.rules["nelson1_beyond_3s"]


def test_laney_c_reduces_false_alarms_on_overdispersed_counts():
    rng = np.random.default_rng(1)
    alarms_plain = alarms_laney = 0
    for _ in range(50):
        x = rng.negative_binomial(2, 2 / (2 + 3), 60).astype(float)   # 過度離散，沒有異常
        alarms_plain += spc.c_chart(x, laney=False).anomalous
        alarms_laney += spc.c_chart(x, laney=True).anomalous
    assert alarms_laney < alarms_plain


def test_cusum_locates_shift():
    rng = np.random.default_rng(2)
    x = rng.normal(0, 1, 80)
    x[40:] += 1.5
    r = changepoint.cusum(x)
    assert r.detected and r.alarm_idx >= 40 and abs(r.change_idx - 40) <= 6
    assert changepoint.lot_at([f"L{i}" for i in range(80)], r.change_idx) == f"L{r.change_idx}"


def test_metrics():
    assert char_accuracy(["ABC"], ["ABC"]) == 1.0
    assert char_accuracy(["ABCD"], ["ABXD"]) == 0.75
    assert row_exact([["a", "b"], ["c", "d"]], [["a", "b"], ["c", "x"]]) == 0.5
    s = detection_scores([
        {"anomalous": True, "detected": True, "change_point": 10, "alarm_idx": 14},
        {"anomalous": True, "detected": False, "change_point": 10, "alarm_idx": None},
        {"anomalous": False, "detected": True, "change_point": None, "alarm_idx": 3},
        {"anomalous": False, "detected": False, "change_point": None, "alarm_idx": None},
    ])
    assert s["detection_rate"] == 0.5 and s["false_alarm_rate"] == 0.5 and s["median_delay"] == 4
