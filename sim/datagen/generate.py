"""產生假機台、圖表、量測值，注入已知異常，並輸出答案卷。

輸出（預設到 sim_data/）：
- legacylab.db       SQLite，給分析與 E6 資料橋接用
- equipment.csv / charts.csv / points.csv   給 LegacyApp（C#）讀
- answer_key.json    每張圖的真實異常類型、變化點、離群點
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

EQUIP_TYPES = ["CVD", "ETCH", "PHOTO", "IMPLANT"]
PARAMS = {
    "CVD": ["THK", "RI", "UNIF"],
    "ETCH": ["CD", "DEPTH", "PARTICLE"],
    "PHOTO": ["OVL_X", "OVL_Y", "DEFECT"],
    "IMPLANT": ["RS", "DOSE", "PARTICLE"],
}
COUNT_PARAMS = {"PARTICLE", "DEFECT"}

# ocr_trap：容易誤判的字元組合
TRAP_TOKENS = ["Å", "O0", "0O", "I1", "1I", "S5", "B8"]

ANOMALY_KINDS = ["shift", "drift", "outlier", "normal"]


@dataclass
class ChartTruth:
    chart_id: str
    equip_id: str
    param: str
    data_kind: str           # "variable" | "count"
    anomaly: str             # shift / drift / outlier / count_shift / normal
    anomalous: bool
    change_point: int | None = None
    outlier_idx: list[int] = field(default_factory=list)
    mean: float = 0.0
    sigma: float = 0.0


def make_equip_id(rng: np.random.Generator, etype: str, n: int, trap_ratio: float) -> str:
    base = f"{etype[:3]}{n:03d}"
    if rng.random() < trap_ratio:
        tok = TRAP_TOKENS[rng.integers(len(TRAP_TOKENS))]
        return f"{base[:3]}{tok}{base[3:]}"
    return base


def variable_series(rng, n, anomaly, mean, sigma):
    x = rng.normal(mean, sigma, n)
    cp, outliers = None, []
    if anomaly == "shift":
        cp = int(rng.integers(n // 3, 2 * n // 3))
        x[cp:] += 1.5 * sigma
    elif anomaly == "drift":
        cp = int(rng.integers(n // 4, n // 2))
        x[cp:] += 0.12 * sigma * np.arange(1, n - cp + 1)
    elif anomaly == "outlier":
        k = int(rng.integers(1, 4))
        outliers = sorted(rng.choice(np.arange(5, n), size=k, replace=False).tolist())
        for i in outliers:
            x[i] = mean + rng.choice([-1, 1]) * 4.5 * sigma
    return x, cp, outliers


def count_series(rng, n, shifted):
    """偏態計數：低 λ 的 Poisson 或負二項；正常的這種資料最容易被 3σ 誤判。"""
    lam = float(rng.uniform(1.0, 3.0))
    if rng.random() < 0.5:
        x = rng.poisson(lam, n).astype(float)
    else:
        r = 3.0
        x = rng.negative_binomial(r, r / (r + lam), n).astype(float)
    cp = None
    if shifted:
        cp = int(rng.integers(n // 3, 2 * n // 3))
        x[cp:] = rng.poisson(lam * 2.5, n - cp)
    return x, cp, lam


def generate(out: Path, seed: int = 42, n_equip: int = 24, charts_per_equip: int = 3,
             points: int = 60, trap_ratio: float = 0.25) -> dict:
    rng = np.random.default_rng(seed)
    out.mkdir(parents=True, exist_ok=True)
    t0 = datetime(2026, 1, 1, 8, 0)

    equipment, charts, rows, truths = [], [], [], []
    for e in range(n_equip):
        etype = EQUIP_TYPES[e % len(EQUIP_TYPES)]
        eid = make_equip_id(rng, etype, e + 1, trap_ratio)
        equipment.append({"equip_id": eid, "equip_type": etype})
        for c in range(charts_per_equip):
            param = PARAMS[etype][c % len(PARAMS[etype])]
            chart_id = f"C{e + 1:03d}{c + 1}"
            if param in COUNT_PARAMS:
                shifted = rng.random() < 0.5
                x, cp, lam = count_series(rng, points, shifted)
                truth = ChartTruth(chart_id, eid, param, "count",
                                   "count_shift" if shifted else "normal", shifted,
                                   cp, [], lam, float(np.sqrt(lam)))
            else:
                anomaly = ANOMALY_KINDS[rng.integers(len(ANOMALY_KINDS))]
                mean = float(rng.uniform(50, 500))
                sigma = float(mean * rng.uniform(0.005, 0.03))
                x, cp, outliers = variable_series(rng, points, anomaly, mean, sigma)
                truth = ChartTruth(chart_id, eid, param, "variable", anomaly,
                                   anomaly != "normal", cp, outliers, mean, sigma)
            truths.append(truth)
            charts.append({"chart_id": chart_id, "equip_id": eid, "param": param,
                           "data_kind": truth.data_kind, "points": points})
            for i, v in enumerate(x):
                ts = t0 + timedelta(hours=6 * i + c)
                lot = f"L{e + 1:02d}{i // 4:03d}"  # 每 4 點一個 batch lot
                rows.append({"chart_id": chart_id, "idx": i, "ts": ts.strftime("%Y-%m-%d %H:%M"),
                             "lot": lot, "value": round(float(v), 4)})

    _write_csv(out / "equipment.csv", equipment)
    _write_csv(out / "charts.csv", charts)
    _write_csv(out / "points.csv", rows)
    _write_sqlite(out / "legacylab.db", equipment, charts, rows)

    key = {"seed": seed, "points": points, "trap_ratio": trap_ratio,
           "charts": [asdict(t) for t in truths]}
    (out / "answer_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    return key


def _write_csv(path: Path, rows: list[dict]) -> None:
    # utf-8-sig：C# 與 Excel 都能正確讀 Å
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _write_sqlite(path: Path, equipment, charts, rows) -> None:
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE equipment(equip_id TEXT PRIMARY KEY, equip_type TEXT);
        CREATE TABLE charts(chart_id TEXT PRIMARY KEY, equip_id TEXT, param TEXT, data_kind TEXT, points INT);
        CREATE TABLE points(chart_id TEXT, idx INT, ts TEXT, lot TEXT, value REAL, PRIMARY KEY(chart_id, idx));
    """)
    con.executemany("INSERT INTO equipment VALUES(:equip_id,:equip_type)", equipment)
    con.executemany("INSERT INTO charts VALUES(:chart_id,:equip_id,:param,:data_kind,:points)", charts)
    con.executemany("INSERT INTO points VALUES(:chart_id,:idx,:ts,:lot,:value)", rows)
    con.commit()
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("sim_data"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--equip", type=int, default=24)
    ap.add_argument("--points", type=int, default=60)
    ap.add_argument("--trap-ratio", type=float, default=0.25)
    a = ap.parse_args()
    key = generate(a.out, a.seed, a.equip, 3, a.points, a.trap_ratio)
    n_bad = sum(c["anomalous"] for c in key["charts"])
    print(f"{len(key['charts'])} charts ({n_bad} anomalous) -> {a.out}")


if __name__ == "__main__":
    main()
