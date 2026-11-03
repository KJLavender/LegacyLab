// LegacyApp：模擬 VB6 舊系統的麻煩之處。
// 用 Windows 內建的 csc.exe（C# 5）編譯，不需要安裝 Visual Studio。
using System;
using System.Collections.Generic;
using System.IO;
using System.Windows.Forms;

namespace LegacyApp
{
    static class Program
    {
        public static AppData Data;
        public static Chaos Chaos;
        public static string DataDir;

        [STAThread]
        static int Main(string[] args)
        {
            Dictionary<string, string> opt = ParseArgs(args);
            string repo = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, @"..\..\.."));
            DataDir = Get(opt, "data", Environment.GetEnvironmentVariable("LEGACYLAB_DATA") ?? Path.Combine(repo, "sim_data"));
            string chaosPath = Get(opt, "chaos", Path.Combine(repo, @"sim\chaos.ini"));

            // VB6 程式沒有 visual styles，維持經典外觀
            Application.SetCompatibleTextRenderingDefault(false);

            Chaos = Chaos.Load(chaosPath, opt.ContainsKey("seed") ? int.Parse(opt["seed"]) : (int?)null);
            try
            {
                Data = AppData.Load(DataDir);
            }
            catch (Exception ex)
            {
                MessageBox.Show("Cannot load data from " + DataDir + "\r\n" + ex.Message, "LegacyApp",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 2;
            }

            MessageBox.Show("LegacyApp Version 3.2.1 (Build 1998.07)\r\nCopyright (C) LegacyLab Simulation",
                "LegacyApp", MessageBoxButtons.OK, MessageBoxIcon.Information);

            string token = Get(opt, "token", null);
            if (!TokenValid(token) || Chaos.Hit(Chaos.TokenExpireProb))
            {
                using (LoginForm login = new LoginForm(repo))
                {
                    if (login.ShowDialog() != DialogResult.OK)
                        return 1;
                }
            }

            Application.Run(new MainForm());
            return 0;
        }

        // tokens.txt 每行：token,到期時間(epoch 秒),功能代碼。驗證成功就刪掉那一行（一次性）。
        static bool TokenValid(string token)
        {
            if (string.IsNullOrEmpty(token)) return false;
            string path = Path.Combine(DataDir, "tokens.txt");
            if (!File.Exists(path)) return false;
            long now = (long)(DateTime.UtcNow - new DateTime(1970, 1, 1)).TotalSeconds;
            bool ok = false;
            List<string> keep = new List<string>();
            foreach (string line in File.ReadAllLines(path))
            {
                string[] p = line.Split(',');
                long exp;
                if (p.Length < 2 || !long.TryParse(p[1], out exp) || exp < now) continue;  // 順便清掉過期的
                if (!ok && p[0] == token) { ok = true; continue; }
                keep.Add(line);
            }
            File.WriteAllLines(path, keep.ToArray());
            return ok;
        }

        static Dictionary<string, string> ParseArgs(string[] args)
        {
            Dictionary<string, string> d = new Dictionary<string, string>();
            for (int i = 0; i < args.Length; i++)
            {
                string a = args[i];
                if (a.StartsWith("legacyapp:", StringComparison.OrdinalIgnoreCase))
                {
                    // 自訂協定啟動：legacyapp://launch?token=xxx
                    int q = a.IndexOf('?');
                    if (q >= 0)
                        foreach (string kv in a.Substring(q + 1).Split('&'))
                        {
                            string[] p = kv.Split(new char[] { '=' }, 2);
                            if (p.Length == 2) d[p[0]] = Uri.UnescapeDataString(p[1]);
                        }
                }
                else if (a.StartsWith("--") && i + 1 < args.Length)
                {
                    d[a.Substring(2)] = args[++i];
                }
            }
            return d;
        }

        static string Get(Dictionary<string, string> d, string k, string def)
        {
            string v;
            return d.TryGetValue(k, out v) ? v : def;
        }
    }
}
