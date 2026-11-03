using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace LegacyApp
{
    class LoginForm : Form
    {
        TextBox txtUser, txtPass;
        Dictionary<string, string> users = new Dictionary<string, string>();

        public LoginForm(string repo)
        {
            // 帳密只放在本機設定檔；沒有 users.ini 時用範例檔
            string path = Path.Combine(repo, @"sim\legacyapp\users.ini");
            if (!File.Exists(path)) path = Path.Combine(repo, @"sim\legacyapp\users.ini.example");
            if (File.Exists(path))
                foreach (string line in File.ReadAllLines(path))
                {
                    int eq = line.IndexOf('=');
                    if (eq > 0 && !line.StartsWith(";")) users[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
                }

            Text = "LOGIN";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false; MinimizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(260, 120);

            Controls.Add(new Label { Text = "User ID", Location = new Point(12, 15), AutoSize = true });
            Controls.Add(new Label { Text = "Password", Location = new Point(12, 45), AutoSize = true });
            txtUser = new TextBox { Location = new Point(90, 12), Width = 150 };
            txtPass = new TextBox { Location = new Point(90, 42), Width = 150, PasswordChar = '*' };
            Button ok = new Button { Text = "OK", Location = new Point(84, 80), Width = 75 };
            Button cancel = new Button { Text = "Cancel", Location = new Point(165, 80), Width = 75, DialogResult = DialogResult.Cancel };
            ok.Click += delegate
            {
                string pw;
                if (users.TryGetValue(txtUser.Text, out pw) && pw == txtPass.Text)
                {
                    DialogResult = DialogResult.OK;
                }
                else
                {
                    MessageBox.Show(this, "Invalid User ID or Password.", "LOGIN", MessageBoxButtons.OK, MessageBoxIcon.Exclamation);
                    txtPass.Text = "";
                }
            };
            Controls.AddRange(new Control[] { txtUser, txtPass, ok, cancel });
            AcceptButton = ok; CancelButton = cancel;
        }
    }

    class BusyForm : Form
    {
        public BusyForm()
        {
            Text = "Please Wait";
            FormBorderStyle = FormBorderStyle.FixedDialog;
            ControlBox = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;
            ClientSize = new Size(240, 60);
            Controls.Add(new Label { Text = "Processing, please wait...", Location = new Point(20, 22), AutoSize = true });
        }
    }

    // 搶焦點用的小通知視窗（混沌模式 focus_steal_prob）
    class NoticeForm : Form
    {
        public NoticeForm()
        {
            Text = "Notice";
            TopMost = true;
            FormBorderStyle = FormBorderStyle.FixedToolWindow;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(220, 50);
            Controls.Add(new Label { Text = "System message received.", Location = new Point(15, 18), AutoSize = true });
            Timer t = new Timer { Interval = 2000 };
            t.Tick += delegate { t.Stop(); Close(); };
            t.Start();
        }
    }

    static class ChaosUi
    {
        // 查詢或開圖途中隨機跳出對話框；一半單按鈕、一半多按鈕（框架不應自動按多按鈕的）
        public static void MaybeDisturb(Form owner)
        {
            Chaos c = Program.Chaos;
            if (c.Hit(c.PopupProb))
            {
                Timer t = new Timer { Interval = 100 + c.Next(400) };
                bool multi = c.Next(2) == 1;
                t.Tick += delegate
                {
                    t.Stop();
                    if (multi)
                        MessageBox.Show(owner, "Connection to server was reset.\r\nReconnect now?", "LegacyApp",
                            MessageBoxButtons.YesNo, MessageBoxIcon.Question);
                    else
                        MessageBox.Show(owner, "Server response is slow.", "LegacyApp",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
                };
                t.Start();
            }
            if (c.Hit(c.FocusStealProb))
                new NoticeForm().Show();
        }

        public static void ApplyDpi(Form f)
        {
            double s = Program.Chaos.DpiScale;
            if (Math.Abs(s - 1.0) < 0.01) return;
            f.Font = new Font(f.Font.FontFamily, (float)(f.Font.Size * s));
            f.Scale(new SizeF((float)s, (float)s));
        }
    }
}
