"""端到端 bench：在三級混沌下跑 bench/tasks/*.yaml，算成功率與耗時，失敗時存現場紀錄。

    .venv\\Scripts\\python -m bench.e2e_bench --levels off,light,heavy --repeats 3
    .venv\\Scripts\\python -m bench.e2e_bench --dialog-rule "Reconnect now?=No"   # 明確允許的對話框規則
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
import traceback
from pathlib import Path

import yaml

from bench.common import ROOT, print_table, save_result
from core.locator import Locator
from core.ocr.base import FallbackOcr
from core.ocr.template import TemplateOcr
from core.trace import Trace
from core.win32 import UnexpectedDialog
from plugins.base import WriteBlocked
from plugins.legacyapp import DEFAULT_DIALOG_RULES, LegacyAppPlugin

DATA = ROOT / "sim_data"
TASKS = ROOT / "bench" / "tasks"
TRACES = ROOT / "bench" / "traces"
EXPORTS = ROOT / "bench" / "traces" / "exports"


# ---------- 答案卷 ----------

def _csv(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class Truth:
    def __init__(self):
        etype = {r["equip_id"]: r["equip_type"] for r in _csv("equipment.csv")}
        self.charts = [{**r, "equip_type": etype[r["equip_id"]]} for r in _csv("charts.csv")]
        self.points: dict[str, list[dict]] = {}
        for r in _csv("points.csv"):
            self.points.setdefault(r["chart_id"], []).append(r)

    def query(self, equip_type="ALL", equip_id="", **_) -> list[dict]:
        return [c for c in self.charts
                if (equip_type == "ALL" or c["equip_type"] == equip_type)
                and (not equip_id or c["equip_id"] == equip_id)]

    def lots(self, prefix: str) -> list[list[str]]:
        """By Lot 頁的預期內容：依圖表順序、lot 出現順序，平均與最大值取 3 位小數。"""
        out = []
        for c in self.charts:
            groups: dict[str, list[float]] = {}
            for p in self.points[c["chart_id"]]:
                if p["lot"].lower().startswith(prefix.lower()):
                    groups.setdefault(p["lot"], []).append(float(p["value"]))
            for lot, v in groups.items():
                out.append([lot, c["chart_id"], c["equip_id"], str(len(v)),
                            _net_f3(sum(v) / len(v)), _net_f3(max(v))])
        return out


def _net_f3(x: float) -> str:
    """和 .NET Framework 的 ToString("F3") 一樣：先取 15 位有效數字，再四捨五入。"""
    from decimal import ROUND_HALF_UP, Decimal

    # .NET Framework 先取 15 位有效數字，再四捨五入
    return str(Decimal(f"{x:.15g}").quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# ---------- 檢查函式 ----------

def ev_export_matches_truth(ctx, truth: Truth) -> str | None:
    path, item = ctx.get("export_path"), ctx.get("export_item")
    if not path:
        return "no export"
    text = Path(path).read_text(encoding="utf-8-sig").splitlines()
    sep = ";" if text[0].count(";") > text[0].count(",") else ","
    rows = list(csv.DictReader(text, delimiter=sep))
    gold = truth.points[item][-len(rows):]
    if len(rows) != len(gold):
        return f"row count {len(rows)} != {len(gold)}"
    for r, g in zip(rows, gold):
        if r["BatchLot"] != g["lot"] or abs(float(r["Value"].replace(",", ".")) - float(g["value"])) > 1e-4:
            return f"mismatch at index {r['Index']}: {r} vs {g}"
    return None


def ev_all_exports_match_truth(ctx, truth: Truth) -> str | None:
    for item, path in ctx.get("exports", []):
        msg = ev_export_matches_truth({"export_item": item, "export_path": path}, truth)
        if msg:
            return f"{item}: {msg}"
    return None if ctx.get("exports") else "no export"


def ev_query_ids_match_truth(ctx, truth: Truth) -> str | None:
    got = [(r["chart_id"], r["equip_id"]) for r in ctx["rows"]]
    exp = [(c["chart_id"], c["equip_id"]) for c in truth.query(**ctx["query_args"])]
    bad = [(e, g) for e, g in zip(exp, got) if e != g]
    if len(got) != len(exp) or bad:
        return f"{len(bad)} wrong rows of {len(exp)}; first: {bad[:3]}"
    return None


def ev_lots_match_truth(ctx, truth: Truth) -> str | None:
    got = [list(r.values()) for r in ctx["lots"]]
    exp = truth.lots(ctx["lot_prefix"])
    bad = [(e, g) for e, g in zip(exp, got) if e != g]
    if len(got) != len(exp) or bad:
        return f"{len(bad)} wrong of {len(exp)} (got {len(got)}); first: {bad[:2]}"
    return None


def ev_write_blocked(ctx, truth) -> str | None:
    return None if ctx.get("write_blocked") else "exclude was NOT blocked"


def ev_no_data_modified(ctx, truth) -> str | None:
    after = (DATA / "excluded.csv").stat().st_size if (DATA / "excluded.csv").exists() else 0
    return None if after == ctx["excluded_before"] else "excluded.csv changed"


def ev_opened_item_title(ctx, truth) -> str | None:
    return None if ctx.get("opened") and ctx["opened"] in ctx.get("opened_title", "") else "wrong chart opened"


EVALUATORS = {k[3:]: v for k, v in globals().items() if k.startswith("ev_")}


# ---------- 執行 ----------

def resolve(item: str, rows: list[dict]) -> str:
    """$first / $last / $N（第 N 列，從 0 起算）或直接寫 chart ID。"""
    if item.startswith("$") and item[1:].isdigit():
        return rows[int(item[1:])]["chart_id"]
    return {"$first": rows[0]["chart_id"], "$last": rows[-1]["chart_id"]}.get(item, item)


def run_task(task: dict, cfg: dict, ocr, truth: Truth, trace: Trace) -> dict:
    ctx: dict = {"excluded_before": (DATA / "excluded.csv").stat().st_size if (DATA / "excluded.csv").exists() else 0}
    t0 = time.perf_counter()
    err = None
    plugin = LegacyAppPlugin({**cfg, **task.get("config", {})}, trace=trace, ocr=ocr)
    try:
        plugin.launch()
        for step in task["actions"]:
            (op, args), = step.items()
            args = dict(args or {})
            if op == "query":
                ctx["query_args"] = args
                ctx["rows"] = plugin.query(**args)
            elif op == "open":
                ctx["opened"] = resolve(args["item"], ctx["rows"])
                plugin.open_item(ctx["opened"])
                ctx["opened_title"] = plugin.chart_title()
            elif op == "export":
                ctx["export_item"] = resolve(args["item"], ctx["rows"])
                ctx["export_path"] = plugin.export(ctx["export_item"], EXPORTS)
                ctx.setdefault("exports", []).append((ctx["export_item"], ctx["export_path"]))
            elif op == "analyze":
                ctx["analysis"] = plugin.analyze(ctx["export_path"])
            elif op == "verify":
                # 預設不學習：bench 的每次執行要互相獨立
                ctx["verified"] = plugin.verify_rows(all_rows=args.get("all", False),
                                                     learn=args.get("learn", False))
            elif op == "lots":
                ctx["lot_prefix"] = args["prefix"]
                ctx["lots"] = plugin.query_lots(args["prefix"], mode=args.get("mode", "auto"))
            elif op == "exclude":
                try:
                    plugin.exclude_last_point(resolve(args["item"], ctx["rows"]))
                except WriteBlocked:
                    ctx["write_blocked"] = True
            else:
                raise ValueError(f"unknown action {op}")
        failures = [f"{name}: {msg}" for name in task["evaluate"]
                    if (msg := EVALUATORS[name](ctx, truth))]
        if failures:
            err = "; ".join(failures)
    except UnexpectedDialog as e:
        err = f"UnexpectedDialog: {e}"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        trace.steps.append({"name": "exception", "traceback": traceback.format_exc()})
    finally:
        plugin.close()
    trace_path = trace.save() if err else None
    return {"ok": err is None, "error": err, "seconds": round(time.perf_counter() - t0, 2),
            "dismissed": plugin.dismissed, "logins": plugin.logins, "verified": ctx.get("verified"),
            "relogins": plugin.relogins, "retries": plugin.retries, "trace": str(trace_path) if trace_path else None,
            "analysis": ctx.get("analysis")}


def build_ocr():
    engines = []
    tpl_path = ROOT / "ocr_templates" / "legacyapp.json"
    if tpl_path.exists():
        engines.append(TemplateOcr.load(tpl_path))
    try:
        from core.ocr.rapid import RapidOcr
        engines.append(RapidOcr())
    except ImportError:
        pass
    if not engines:
        raise SystemExit("no OCR engine: run bench.ocr_bench first, or pip install -e .[ocr]")
    return FallbackOcr(*engines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", default="off,light,heavy")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--tasks", default="all")
    ap.add_argument("--seed", type=int, default=100)
    ap.add_argument("--dpi", type=float, default=1.0)
    ap.add_argument("--dialog-rule", action="append", default=[], help='"內文片段=按鈕"，可重複；加在預設規則之上')
    ap.add_argument("--no-default-rules", action="store_true", help="不用預設的對話框規則（測最嚴格的情況）")
    ap.add_argument("--portal", action="store_true", help="透過假入口網站 + 一次性 token 啟動")
    ap.add_argument("--cache", action="store_true",
                    help="開圖確認過的儲存格跨次共用（第一次建立，之後命中；看快取省多少時間）")
    ap.add_argument("--portal-port", type=int, default=8765)
    a = ap.parse_args()

    rules = {} if a.no_default_rules else dict(DEFAULT_DIALOG_RULES)
    rules.update(dict(r.split("=", 1) for r in a.dialog_rule))
    files = sorted(TASKS.glob("*.yaml"))
    tasks = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in files]
    if a.tasks != "all":
        tasks = [t for t in tasks if t["id"] in a.tasks.split(",")]
    truth, ocr = Truth(), build_ocr()
    if a.cache:
        (TRACES / "verified_cache.json").unlink(missing_ok=True)   # 每次 bench 從空快取開始
    portal, server = None, None
    if a.portal:
        server = subprocess.Popen([sys.executable, "-m", "sim.portal.app", "--port", str(a.portal_port)], cwd=ROOT)
        time.sleep(2)
        portal = {"portal_url": f"http://127.0.0.1:{a.portal_port}", "func": "CHART", "scheme": "legacyapp",
                  "handler": [sys.executable, str(ROOT / "sim/launcher/handler.py")]}

    runs, summary = [], []
    for level in a.levels.split(","):
        for task in tasks:
            res = []
            for r in range(a.repeats):
                seed = a.seed + r
                cfg = {"chaos": level, "seed": seed, "dialog_rules": rules,
                       "chaos_overrides": {"dpi_scale": a.dpi} if a.dpi != 1.0 else {}}
                if portal:
                    cfg["portal"] = portal
                if a.cache:
                    cfg["verified_cache"] = str(TRACES / "verified_cache.json")
                trace = Trace(TRACES, f"{task['id']}-{level}-{seed}")
                out = run_task(task, cfg, ocr, truth, trace)
                res.append(out)
                runs.append({"task": task["id"], "level": level, "seed": seed, **out})
                print(f"  {level:5s} {task['id']:22s} seed={seed} {'OK ' if out['ok'] else 'FAIL'} "
                      f"{out['seconds']:5.1f}s {out['error'] or ''}")
            ok = [x for x in res if x["ok"]]
            summary.append({"level": level, "task": task["id"], "success": len(ok) / len(res),
                            "avg_seconds": sum(x["seconds"] for x in ok) / len(ok) if ok else None,
                            "popups_dismissed": sum(len(x["dismissed"]) for x in res),
                            "login_fallbacks": sum(1 for x in res if x["logins"]) if portal else None,
                            "relogins": sum(x["relogins"] for x in res), "retries": sum(x["retries"] for x in res)})
    if server:
        server.terminate()
    print()
    print_table(summary, ["level", "task", "success", "avg_seconds", "popups_dismissed", "login_fallbacks",
                          "relogins", "retries"])
    print("locator layers:", Locator.report())
    print("ocr engine usage:", ocr.used)
    print("saved:", save_result("e2e", a.seed, {"dpi": a.dpi, "dialog_rules": rules, "portal": bool(portal),
                                                "summary": summary,
                                                "runs": runs, "locator": Locator.report(), "ocr_usage": ocr.used}))


if __name__ == "__main__":
    main()
