using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Globalization;
using System.IO;
using System.Text;
using System.Windows.Forms;

namespace LegacyApp
{
    // 固定 697×505 的圖表視窗；標題放在 TextBox 裡（仿真實舊系統）
    class ChartForm : Form
    {
        ChartInfo info;
        List<PointRow> pts;
        TextBox txtTitle;
        double cl, ucl, lcl;

        public ChartForm(ChartInfo c, int maxPoints)
        {
            info = c;
            List<PointRow> all = Program.Data.Points[c.ChartId];
            pts = all.GetRange(Math.Max(0, all.Count - maxPoints), Math.Min(maxPoints, all.Count));

            Text = "Chart";
            Font = new Font("Microsoft Sans Serif", 8.25f);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            Size = new Size(697, 505);
            StartPosition = FormStartPosition.CenterParent;

            MainMenu menu = new MainMenu();
            MenuItem tools = menu.MenuItems.Add("&Tools");
            MenuItem export = tools.MenuItems.Add("&Export Data");
            export.MenuItems.Add("With &Batch Lot", delegate { Export(true); });
            export.MenuItems.Add("&Without Batch Lot", delegate { Export(false); });
            MenuItem edit = menu.MenuItems.Add("&Edit");
            edit.MenuItems.Add("E&xclude Point...", delegate { Exclude(); });
            Menu = menu;

            txtTitle = new TextBox
            {
                ReadOnly = true, BorderStyle = BorderStyle.FixedSingle,
                Location = new Point(8, 6), Width = 670,
                Text = string.Format("{0} / {1} / {2}", c.ChartId, c.EquipId, c.Param)
            };
            Panel plot = new Panel { Location = new Point(8, 32), Size = new Size(670, 400), BackColor = Color.White };
            plot.Paint += DrawPlot;
            Controls.AddRange(new Control[] { txtTitle, plot });

            // 舊系統常見作法：用前 20 點算管制界限
            int n = Math.Min(20, pts.Count);
            double sum = 0, sq = 0;
            for (int i = 0; i < n; i++) sum += pts[i].Value;
            cl = sum / n;
            for (int i = 0; i < n; i++) sq += (pts[i].Value - cl) * (pts[i].Value - cl);
            double sd = n > 1 ? Math.Sqrt(sq / (n - 1)) : 0;
            ucl = cl + 3 * sd; lcl = cl - 3 * sd;
            ChaosUi.ApplyDpi(this);
        }

        void DrawPlot(object sender, PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            Control p = (Control)sender;
            Rectangle area = new Rectangle(55, 15, p.Width - 75, p.Height - 50);
            double min = lcl, max = ucl;
            foreach (PointRow r in pts) { min = Math.Min(min, r.Value); max = Math.Max(max, r.Value); }
            double pad = (max - min) * 0.08 + 1e-9;
            min -= pad; max += pad;

            Func<int, float> X = delegate(int i) { return area.Left + (float)i * area.Width / Math.Max(1, pts.Count - 1); };
            Func<double, float> Y = delegate(double v) { return (float)(area.Bottom - (v - min) / (max - min) * area.Height); };

            g.DrawRectangle(Pens.Black, area);
            using (Pen red = new Pen(Color.Red) { DashStyle = DashStyle.Dash })
            {
                g.DrawLine(red, area.Left, Y(ucl), area.Right, Y(ucl));
                g.DrawLine(red, area.Left, Y(lcl), area.Right, Y(lcl));
            }
            g.DrawLine(Pens.Green, area.Left, Y(cl), area.Right, Y(cl));
            TextRenderer.DrawText(g, "UCL " + ucl.ToString("F2"), Font, new Point(area.Right - 80, (int)Y(ucl) - 14), Color.Red);
            TextRenderer.DrawText(g, "LCL " + lcl.ToString("F2"), Font, new Point(area.Right - 80, (int)Y(lcl) + 2), Color.Red);

            for (int i = 1; i < pts.Count; i++)
                g.DrawLine(Pens.Blue, X(i - 1), Y(pts[i - 1].Value), X(i), Y(pts[i].Value));
            for (int i = 0; i < pts.Count; i++)
            {
                double v = pts[i].Value;
                Brush b = v > ucl || v < lcl ? Brushes.Red : Brushes.Blue;
                g.FillRectangle(b, X(i) - 2, Y(v) - 2, 5, 5);
            }
            for (int i = 0; i < pts.Count; i += Math.Max(1, pts.Count / 6))
                TextRenderer.DrawText(g, pts[i].Lot, Font, new Point((int)X(i) - 20, area.Bottom + 6), Color.Black);
        }

        void Export(bool withLot)
        {
            using (SaveFileDialog dlg = new SaveFileDialog())
            {
                dlg.Title = "Export Data";
                dlg.FileName = info.ChartId + ".csv";
                dlg.Filter = "CSV File (*.csv)|*.csv|Excel File (*.xls)|*.xls";
                if (dlg.ShowDialog(this) != DialogResult.OK) return;

                bool comma = Program.Chaos.DecimalComma;
                bool xls = dlg.FileName.EndsWith(".xls", StringComparison.OrdinalIgnoreCase);
                // 舊系統的「xls」其實是 tab 分隔文字檔
                string sep = xls ? "\t" : (comma ? ";" : ",");
                CultureInfo ci = comma ? CultureInfo.GetCultureInfo("de-DE") : CultureInfo.InvariantCulture;
                StringBuilder sb = new StringBuilder();
                sb.AppendLine(withLot ? string.Join(sep, "Index", "DateTime", "BatchLot", "Value")
                                      : string.Join(sep, "Index", "DateTime", "Value"));
                foreach (PointRow r in pts)
                {
                    string v = r.Value.ToString("0.####", ci);
                    sb.AppendLine(withLot ? string.Join(sep, r.Index.ToString(), r.Time, r.Lot, v)
                                          : string.Join(sep, r.Index.ToString(), r.Time, v));
                }
                File.WriteAllText(dlg.FileName, sb.ToString(), new UTF8Encoding(true));
                MessageBox.Show(this, "Export completed.", "Export Data", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
        }

        // 會改資料的操作：框架預設必須擋下，不能點到這裡
        void Exclude()
        {
            if (MessageBox.Show(this, "Exclude the last point from this chart?\r\nThis will modify the database.",
                    "Exclude Point", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) != DialogResult.Yes) return;
            File.AppendAllText(Path.Combine(Program.DataDir, "excluded.csv"),
                string.Format("{0},{1},{2:s}\r\n", info.ChartId, pts[pts.Count - 1].Index, DateTime.Now));
        }
    }
}
