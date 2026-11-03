using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace LegacyApp
{
    class ChartInfo
    {
        public string ChartId, EquipId, EquipType, Param, DataKind;
        public int Points;
    }

    class PointRow
    {
        public int Index;
        public string Time, Lot;
        public double Value;
    }

    class AppData
    {
        public List<ChartInfo> Charts = new List<ChartInfo>();
        public Dictionary<string, List<PointRow>> Points = new Dictionary<string, List<PointRow>>();
        public List<string> EquipTypes = new List<string>();

        public static AppData Load(string dir)
        {
            AppData d = new AppData();
            Dictionary<string, string> typeOf = new Dictionary<string, string>();
            foreach (string[] r in ReadCsv(Path.Combine(dir, "equipment.csv")))
            {
                typeOf[r[0]] = r[1];
                if (!d.EquipTypes.Contains(r[1])) d.EquipTypes.Add(r[1]);
            }
            foreach (string[] r in ReadCsv(Path.Combine(dir, "charts.csv")))
            {
                ChartInfo c = new ChartInfo();
                c.ChartId = r[0]; c.EquipId = r[1]; c.Param = r[2]; c.DataKind = r[3];
                c.Points = int.Parse(r[4]);
                c.EquipType = typeOf[c.EquipId];
                d.Charts.Add(c);
            }
            foreach (string[] r in ReadCsv(Path.Combine(dir, "points.csv")))
            {
                List<PointRow> list;
                if (!d.Points.TryGetValue(r[0], out list))
                {
                    list = new List<PointRow>();
                    d.Points[r[0]] = list;
                }
                PointRow p = new PointRow();
                p.Index = int.Parse(r[1]); p.Time = r[2]; p.Lot = r[3];
                p.Value = double.Parse(r[4], CultureInfo.InvariantCulture);
                list.Add(p);
            }
            return d;
        }

        static IEnumerable<string[]> ReadCsv(string path)
        {
            string[] lines = File.ReadAllLines(path, Encoding.UTF8);
            for (int i = 1; i < lines.Length; i++)
                if (lines[i].Length > 0) yield return lines[i].Split(',');
        }
    }

    // 混沌模式：讀 sim/chaos.ini，level 決定預設值，個別鍵可覆寫
    class Chaos
    {
        public string Level = "off";
        public int DelayMinMs = 500, DelayMaxMs = 1000;
        public double PopupProb, TokenExpireProb, FocusStealProb;
        public double DpiScale = 1.0;
        public bool DecimalComma;
        Random rng;

        public static Chaos Load(string path, int? seedOverride)
        {
            Dictionary<string, string> kv = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (File.Exists(path))
                foreach (string raw in File.ReadAllLines(path))
                {
                    string line = raw.Trim();
                    if (line.Length == 0 || line[0] == ';' || line[0] == '#' || line[0] == '[') continue;
                    int eq = line.IndexOf('=');
                    if (eq > 0) kv[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
                }
            string envLevel = Environment.GetEnvironmentVariable("LEGACYLAB_CHAOS");
            if (!string.IsNullOrEmpty(envLevel)) kv["level"] = envLevel;
            // LEGACYLAB_CHAOS_<KEY>=value 可覆寫任何一項，例如 LEGACYLAB_CHAOS_DPI_SCALE=1.25
            foreach (System.Collections.DictionaryEntry e in Environment.GetEnvironmentVariables())
            {
                string name = (string)e.Key;
                if (name.StartsWith("LEGACYLAB_CHAOS_", StringComparison.OrdinalIgnoreCase))
                    kv[name.Substring(16).ToLowerInvariant()] = (string)e.Value;
            }

            Chaos c = new Chaos();
            string level;
            if (kv.TryGetValue("level", out level)) c.Level = level.ToLowerInvariant();
            if (c.Level == "light")
            {
                c.DelayMinMs = 1000; c.DelayMaxMs = 3000;
                c.PopupProb = 0.1; c.TokenExpireProb = 0.1; c.FocusStealProb = 0.05;
            }
            else if (c.Level == "heavy")
            {
                c.DelayMinMs = 1000; c.DelayMaxMs = 5000;
                c.PopupProb = 0.3; c.TokenExpireProb = 0.3; c.FocusStealProb = 0.15;
            }
            c.DelayMinMs = GetInt(kv, "delay_min_ms", c.DelayMinMs);
            c.DelayMaxMs = GetInt(kv, "delay_max_ms", c.DelayMaxMs);
            c.PopupProb = GetDouble(kv, "popup_prob", c.PopupProb);
            c.TokenExpireProb = GetDouble(kv, "token_expire_prob", c.TokenExpireProb);
            c.FocusStealProb = GetDouble(kv, "focus_steal_prob", c.FocusStealProb);
            c.DpiScale = GetDouble(kv, "dpi_scale", c.DpiScale);
            c.DecimalComma = GetInt(kv, "decimal_comma", 0) != 0;
            int seed = seedOverride ?? GetInt(kv, "seed", Environment.TickCount);
            c.rng = new Random(seed);
            return c;
        }

        public bool Hit(double p) { return p > 0 && rng.NextDouble() < p; }
        public int Delay() { return rng.Next(DelayMinMs, Math.Max(DelayMinMs + 1, DelayMaxMs)); }
        public int Next(int max) { return rng.Next(max); }

        static int GetInt(Dictionary<string, string> kv, string k, int def)
        {
            string v; int r;
            return kv.TryGetValue(k, out v) && int.TryParse(v, out r) ? r : def;
        }

        static double GetDouble(Dictionary<string, string> kv, string k, double def)
        {
            string v; double r;
            return kv.TryGetValue(k, out v) && double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out r) ? r : def;
        }
    }
}
