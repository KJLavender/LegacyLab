using System;
using System.Collections.Generic;
using System.Drawing;
using System.Windows.Forms;

namespace LegacyApp
{
    class MainForm : Form
    {
        TextBox txtEquip, txtDays, txtPoints;
        ComboBox cboType;
        Button btnQuery;
        ResultGrid grid;
        StatusBar status;
        ChartForm chart;

        public MainForm()
        {
            Text = "LegacyApp - View By Equipment";
            Font = new Font("Microsoft Sans Serif", 8.25f);
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(560, 520);

            // MainMenu 是原生 Win32 選單（和 VB6 一樣），可以用 GetMenu / WM_COMMAND 操作
            MainMenu menu = new MainMenu();
            MenuItem file = menu.MenuItems.Add("&File");
            file.MenuItems.Add("E&xit", delegate { Close(); });
            MenuItem help = menu.MenuItems.Add("&Help");
            help.MenuItems.Add("&About", delegate
            {
                MessageBox.Show(this, "LegacyApp Version 3.2.1", "About", MessageBoxButtons.OK, MessageBoxIcon.Information);
            });
            Menu = menu;

            GroupBox box = new GroupBox { Text = "View By Equipment", Location = new Point(8, 6), Size = new Size(544, 76) };
            box.Controls.Add(new Label { Text = "EquipmentID", Location = new Point(10, 22), AutoSize = true });
            txtEquip = new TextBox { Location = new Point(10, 40), Width = 120 };
            box.Controls.Add(new Label { Text = "EquipType", Location = new Point(140, 22), AutoSize = true });
            cboType = new ComboBox { Location = new Point(140, 40), Width = 90, DropDownStyle = ComboBoxStyle.DropDownList };
            cboType.Items.Add("ALL");
            foreach (string t in Program.Data.EquipTypes) cboType.Items.Add(t);
            cboType.SelectedIndex = 0;
            box.Controls.Add(new Label { Text = "Days", Location = new Point(240, 22), AutoSize = true });
            txtDays = new TextBox { Location = new Point(240, 40), Width = 50, Text = "30" };
            box.Controls.Add(new Label { Text = "Points", Location = new Point(300, 22), AutoSize = true });
            txtPoints = new TextBox { Location = new Point(300, 40), Width = 50, Text = "60" };
            btnQuery = new Button { Text = "Query", Location = new Point(450, 38), Width = 80 };
            btnQuery.Click += delegate { RunQuery(); };
            box.Controls.AddRange(new Control[] { txtEquip, cboType, txtDays, txtPoints, btnQuery });

            grid = new ResultGrid { Location = new Point(8, 90), Size = new Size(544, 400) };
            grid.RowActivated += OpenChart;

            status = new StatusBar { Text = "Ready" };
            Controls.AddRange(new Control[] { box, grid, status });
            AcceptButton = btnQuery;
            ChaosUi.ApplyDpi(this);
        }

        void RunQuery()
        {
            btnQuery.Enabled = false;
            status.Text = "Searching...";
            BusyForm busy = new BusyForm();
            busy.Show(this);
            ChaosUi.MaybeDisturb(this);

            Timer t = new Timer { Interval = Program.Chaos.Delay() };
            t.Tick += delegate
            {
                t.Stop();
                List<ChartInfo> rows = new List<ChartInfo>();
                string equip = txtEquip.Text.Trim();
                string type = (string)cboType.SelectedItem;
                foreach (ChartInfo c in Program.Data.Charts)
                {
                    if (equip.Length > 0 && c.EquipId.IndexOf(equip, StringComparison.OrdinalIgnoreCase) < 0) continue;
                    if (type != "ALL" && c.EquipType != type) continue;
                    rows.Add(c);
                }
                grid.SetRows(rows);
                busy.Close();
                btnQuery.Enabled = true;
                status.Text = rows.Count + " record(s) found";
            };
            t.Start();
        }

        void OpenChart(ChartInfo c)
        {
            if (chart != null && !chart.IsDisposed) chart.Close();
            int maxPoints;
            if (!int.TryParse(txtPoints.Text, out maxPoints) || maxPoints <= 0) maxPoints = c.Points;

            BusyForm busy = new BusyForm();
            busy.Show(this);
            ChaosUi.MaybeDisturb(this);
            Timer t = new Timer { Interval = Program.Chaos.Delay() / 2 };
            t.Tick += delegate
            {
                t.Stop();
                busy.Close();
                chart = new ChartForm(c, maxPoints);
                chart.Show(this);
            };
            t.Start();
        }
    }

    // 自繪表格：沒有任何子控制項或 API 可讀，只能擷圖 + OCR（或攔截 GDI 文字）
    class ResultGrid : Control
    {
        public static readonly string[] Headers = { "Chart ID", "Equipment ID", "Parameter", "Kind", "Points" };
        public static readonly int[] Widths = { 80, 130, 100, 90, 70 };
        public const int HeaderHeight = 20, RowHeight = 18;

        public event Action<ChartInfo> RowActivated;
        List<ChartInfo> rows = new List<ChartInfo>();
        int top, selected = -1;

        public ResultGrid()
        {
            SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer |
                     ControlStyles.UserPaint | ControlStyles.Selectable, true);
            BackColor = Color.White;
            TabStop = true;
        }

        public void SetRows(List<ChartInfo> r) { rows = r; top = 0; selected = r.Count > 0 ? 0 : -1; Invalidate(); }

        int VisibleRows { get { return Math.Max(1, (Height - HeaderHeight - 2) / RowHeight); } }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.Clear(Color.White);
            ControlPaint.DrawBorder3D(g, ClientRectangle, Border3DStyle.Sunken);
            int x = 2;
            for (int c = 0; c < Headers.Length; c++)
            {
                Rectangle r = new Rectangle(x, 2, Widths[c], HeaderHeight);
                g.FillRectangle(SystemBrushes.Control, r);
                ControlPaint.DrawBorder3D(g, r, Border3DStyle.RaisedInner);
                // TextRenderer 走 GDI（ExtTextOut），和 VB6 自繪一樣
                TextRenderer.DrawText(g, Headers[c], Font, new Rectangle(r.X + 4, r.Y, r.Width - 4, r.Height),
                    Color.Black, TextFormatFlags.VerticalCenter | TextFormatFlags.Left);
                x += Widths[c];
            }
            for (int i = 0; i < VisibleRows && top + i < rows.Count; i++)
            {
                ChartInfo ci = rows[top + i];
                int y = 2 + HeaderHeight + i * RowHeight;
                bool sel = top + i == selected;
                if (sel) g.FillRectangle(SystemBrushes.Highlight, 2, y, Width - 4, RowHeight);
                string[] cells = { ci.ChartId, ci.EquipId, ci.Param, ci.DataKind, ci.Points.ToString() };
                x = 2;
                for (int c = 0; c < cells.Length; c++)
                {
                    TextRenderer.DrawText(g, cells[c], Font, new Rectangle(x + 4, y, Widths[c] - 4, RowHeight),
                        sel ? SystemColors.HighlightText : Color.Black, TextFormatFlags.VerticalCenter | TextFormatFlags.Left);
                    x += Widths[c];
                }
                g.DrawLine(Pens.Gainsboro, 2, y + RowHeight - 1, Width - 3, y + RowHeight - 1);
            }
            if (rows.Count > VisibleRows)
            {
                // 頁碼畫在表頭右側空白處，不蓋到資料列
                string more = string.Format("{0}-{1} / {2}", top + 1, Math.Min(rows.Count, top + VisibleRows), rows.Count);
                TextRenderer.DrawText(g, more, Font, new Rectangle(x + 4, 2, Width - x - 8, HeaderHeight), Color.Gray,
                    TextFormatFlags.VerticalCenter | TextFormatFlags.Right);
            }
        }

        int RowAt(int y)
        {
            int i = (y - 2 - HeaderHeight) / RowHeight;
            return y > 2 + HeaderHeight && top + i < rows.Count ? top + i : -1;
        }

        // 雙擊在 MouseDown 用 Clicks 判斷，和 VB6 的 DblClick 一樣：收到 WM_LBUTTONDBLCLK 就觸發。
        // （WinForms 的 OnMouseDoubleClick 會另外檢查實際游標位置，背景送訊息會失效，VB6 沒有這個行為。）
        protected override void OnMouseDown(MouseEventArgs e)
        {
            Focus();
            int r = RowAt(e.Y);
            if (r >= 0) { selected = r; Invalidate(); }
            base.OnMouseDown(e);
            if (e.Clicks >= 2 && r >= 0 && RowActivated != null) RowActivated(rows[r]);
        }

        protected override void OnMouseWheel(MouseEventArgs e) { Scroll(e.Delta > 0 ? -3 : 3); }

        protected override bool IsInputKey(Keys k)
        {
            return k == Keys.Up || k == Keys.Down || k == Keys.PageUp || k == Keys.PageDown || base.IsInputKey(k);
        }

        protected override void OnKeyDown(KeyEventArgs e)
        {
            if (rows.Count == 0) return;
            int step = 0;
            if (e.KeyCode == Keys.Down) step = 1;
            else if (e.KeyCode == Keys.Up) step = -1;
            else if (e.KeyCode == Keys.PageDown || e.KeyCode == Keys.PageUp)
            {
                // 整頁捲動：top 一次移動一整頁
                int d = e.KeyCode == Keys.PageDown ? VisibleRows : -VisibleRows;
                Scroll(d);
                selected = Math.Max(0, Math.Min(rows.Count - 1, selected + d));
                return;
            }
            else if (e.KeyCode == Keys.Enter && selected >= 0 && RowActivated != null) { RowActivated(rows[selected]); return; }
            if (step == 0) return;
            selected = Math.Max(0, Math.Min(rows.Count - 1, selected + step));
            if (selected < top) top = selected;
            if (selected >= top + VisibleRows) top = selected - VisibleRows + 1;
            Invalidate();
        }

        void Scroll(int delta)
        {
            top = Math.Max(0, Math.Min(Math.Max(0, rows.Count - VisibleRows), top + delta));
            Invalidate();
        }
    }
}
