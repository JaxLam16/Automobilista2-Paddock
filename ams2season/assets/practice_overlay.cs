// Passive external overlay: never activates, injects inputs, hooks or writes to AMS2.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class GarageOverlay : Form {
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    readonly string path;
    readonly Process parent;
    readonly Timer timer = new Timer();
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    readonly Label title = new Label(), location = new Label(), action = new Label(), detail = new Label(), why = new Label(), choices = new Label(), footer = new Label();
    protected override bool ShowWithoutActivation { get { return true; } }
    protected override CreateParams CreateParams { get {
        CreateParams p = base.CreateParams;
        p.ExStyle |= 0x08000000 | 0x00000080 | 0x00000020; // NOACTIVATE, TOOLWINDOW, click-through
        return p;
    }}
    static string TextOf(Dictionary<string,object> d, string k) { object v; return d.TryGetValue(k,out v) && v != null ? Convert.ToString(v) : ""; }
    static bool Yes(Dictionary<string,object> d, string k) { object v; return d.TryGetValue(k,out v) && v is bool && (bool)v; }
    internal GarageOverlay(string statePath, int parentId) {
        path = statePath;
        if (parentId > 0) parent = Process.GetProcessById(parentId);
        AutoScaleMode = AutoScaleMode.Dpi; FormBorderStyle = FormBorderStyle.None;
        ShowInTaskbar = false; TopMost = true; StartPosition = FormStartPosition.Manual;
        BackColor = Color.FromArgb(20,26,33); ForeColor = Color.FromArgb(233,238,245);
        Width = 470; Height = 390; Opacity = .96;
        Label[] labels = {title,location,action,detail,why,choices,footer};
        int[] tops = {18,52,84,146,200,270,314};
        int[] heights = {28,26,60,52,64,160,62};
        for (int i=0;i<labels.Length;i++) {
            Label l=labels[i]; l.SetBounds(20,tops[i],430,heights[i]);
            l.Font=new Font("Segoe UI", i==2?16:i==0?12:i==6?9:10, i==0||i==2?FontStyle.Bold:FontStyle.Regular);
            l.AutoEllipsis=true; l.UseMnemonic=false; Controls.Add(l);
        }
        location.ForeColor=choices.ForeColor=Color.FromArgb(95,205,207); footer.ForeColor=Color.FromArgb(172,184,199);
        timer.Interval=150; timer.Tick += delegate { RefreshState(); }; timer.Start();
    }
    internal void Apply(Dictionary<string,object> d) {
        object raw; Dictionary<string,object> c = d.TryGetValue("card",out raw)?raw as Dictionary<string,object>:null;
        if(c==null)c=new Dictionary<string,object>();
        int n=0; Int32.TryParse(TextOf(d,"index"),out n);
        title.Text="PADDOCK  •  "+(n+1)+" / "+TextOf(d,"total")+"   "+(TextOf(c,"kind")=="rd"?"R&D":"SETUP");
        location.Text=TextOf(c,"location");
        action.Text=TextOf(c,"heading")+"\n"+TextOf(c,"action");
        detail.Text=TextOf(c,"detail"); why.Text=TextOf(c,"why");
        int selected=0;Int32.TryParse(TextOf(d,"menu_index"),out selected);
        var menu=d.TryGetValue("menu",out raw)?raw as System.Collections.IEnumerable:null;
        choices.Text=Yes(d,"pending")?"Saving decision…":"";
        int menuPosition=0;
        if(menu!=null&&!Yes(d,"pending"))foreach(object entry in menu){
            var item=entry as Dictionary<string,object>;
            if(item!=null)choices.Text+=(menuPosition==selected?"▶  ":"     ")+TextOf(item,"label")+"\n";
            menuPosition++;
        }
        footer.Text=TextOf(c,"tag")+"\n"+TextOf(d,"controls")+"\nLeft/right: instruction • Up/down: action • Confirm: select";
        if(TextOf(d,"note")!="")footer.Text+="\n"+TextOf(d,"note");
        int y=18;
        Label[] labels={title,location,action,detail,why,choices,footer};
        foreach(Label l in labels){
            int needed=TextRenderer.MeasureText(l.Text,l.Font,new Size(430,1000),TextFormatFlags.WordBreak|TextFormatFlags.TextBoxControl).Height+6;
            l.SetBounds(20,y,430,Math.Min(l==why?150:200,Math.Max(24,needed)));y+=l.Height+8;
        }
        Height=y+10;
        Rectangle area=Screen.FromHandle(GetForegroundWindow()).WorkingArea;
        int margin=16; Location=new Point(TextOf(d,"position")=="left"?area.Left+margin:area.Right-Width-margin,area.Top+margin);
    }
    void RefreshState() {
        try {
            if(parent!=null&&parent.HasExited){timer.Stop();Application.ExitThread();return;}
            var d=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));
            object raw; double expires=d.TryGetValue("expires_utc",out raw)?Convert.ToDouble(raw,System.Globalization.CultureInfo.InvariantCulture):0;
            uint pid; GetWindowThreadProcessId(GetForegroundWindow(),out pid);
            string name=pid==0?"":Process.GetProcessById((int)pid).ProcessName;
            bool ams2=name.Equals("AMS2AVX",StringComparison.OrdinalIgnoreCase)||name.Equals("AMS2",StringComparison.OrdinalIgnoreCase);
            bool live=Yes(d,"enabled")&&Yes(d,"visible")&&expires>(DateTime.UtcNow-new DateTime(1970,1,1)).TotalSeconds&&ams2;
            if(!live){Hide();return;}
            Apply(d); if(!Visible)Show();
        } catch { Hide(); }
    }
    protected override void OnFormClosed(FormClosedEventArgs e){timer.Stop();timer.Dispose();if(parent!=null)parent.Dispose();base.OnFormClosed(e);Application.ExitThread();}
    [STAThread] static int Main(string[] args) {
        try {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            if(args.Length==3&&args[0]=="--render") {
                using(var f=new GarageOverlay(args[1],0)) {
                    f.timer.Stop(); f.Apply(f.json.Deserialize<Dictionary<string,object>>(File.ReadAllText(args[1])));
                    f.CreateControl(); using(var image=new Bitmap(f.Width,f.Height)){
                        using(Graphics canvas=Graphics.FromImage(image)){
                            canvas.Clear(f.BackColor);
                            // Hidden parent forms omit children from DrawToBitmap. Render each
                            // actual label separately so the preview never opens a desktop window.
                            foreach(Control child in f.Controls){
                                using(var part=new Bitmap(child.Width,child.Height)){
                                    child.DrawToBitmap(part,new Rectangle(0,0,child.Width,child.Height));
                                    canvas.DrawImageUnscaled(part,child.Location);
                                }
                            }
                        }
                        image.Save(args[2]);
                    }
                    File.WriteAllText(args[2]+".labels.json",f.json.Serialize(new {menu=f.choices.Text,height=f.Height,
                        footer=f.footer.Text,heading=f.action.Text,no_activation=f.ShowWithoutActivation}));
                } return 0;
            }
            if(args.Length!=2)return 2;
            using(var overlay=new GarageOverlay(args[0],Int32.Parse(args[1]))) {
                // Running a form directly would show it before the first telemetry check.
                Application.Run(new ApplicationContext());
            }
            return 0;
        } catch {return 1;}
    }
}
