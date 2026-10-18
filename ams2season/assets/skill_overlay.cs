// Passive external skill panel. No activation, input hooks, game writes or audio.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal sealed class SkillPanel : Form {
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
    readonly string path; readonly Process parent; readonly Timer timer=new Timer();
    readonly JavaScriptSerializer json=new JavaScriptSerializer();
    Dictionary<string,object> state=new Dictionary<string,object>();
    protected override bool ShowWithoutActivation {get{return true;}}
    protected override CreateParams CreateParams {get {var p=base.CreateParams;p.ExStyle|=0x08000000|0x00000080|0x00000020;return p;}}
    static string Txt(Dictionary<string,object> d,string k){object v;return d.TryGetValue(k,out v)&&v!=null?Convert.ToString(v):"";}
    static bool Yes(Dictionary<string,object> d,string k){object v;return d.TryGetValue(k,out v)&&v is bool&&(bool)v;}
    static Dictionary<string,object> Obj(Dictionary<string,object> d,string k){object v;return d.TryGetValue(k,out v)&&v is Dictionary<string,object>?(Dictionary<string,object>)v:new Dictionary<string,object>();}
    internal SkillPanel(string file,int pid){
        path=file;if(pid>0)parent=Process.GetProcessById(pid);
        AutoScaleMode=AutoScaleMode.Dpi;FormBorderStyle=FormBorderStyle.None;ShowInTaskbar=false;
        TopMost=true;StartPosition=FormStartPosition.Manual;DoubleBuffered=true;
        BackColor=Color.FromArgb(17,23,31);ForeColor=Color.FromArgb(233,238,245);
        Width=490;Height=350;
        timer.Interval=150;timer.Tick+=delegate{RefreshState();};timer.Start();
    }
    internal void Apply(Dictionary<string,object> d){
        state=d;bool compact=Txt(d,"size")=="compact";Width=compact?460:490;
        double opacity;Opacity=Double.TryParse(Txt(d,"opacity"),out opacity)?Math.Max(.4,Math.Min(1,opacity)):.95;
        var metric=Obj(d,"metric");
        using(var font=new Font("Segoe UI",10)){
            var measured=TextRenderer.MeasureText(Txt(metric,"detail"),font,new Size(Width-40,1000),TextFormatFlags.WordBreak|TextFormatFlags.TextBoxControl);
            Height=compact?110:270+measured.Height;
        }
        Rectangle area=Screen.FromHandle(GetForegroundWindow()).WorkingArea;
        Location=Txt(d,"position")=="center"?new Point(area.Left+(area.Width-Width)/2,area.Top+(area.Height-Height)/2):new Point(Txt(d,"position")=="left"?area.Left+16:area.Right-Width-16,area.Top+16);
        Invalidate();
    }
    void Label(Graphics g,string text,int y,int size,Color color,FontStyle style,int height){
        using(var f=new Font("Segoe UI",size,style))using(var brush=new SolidBrush(color))
            g.DrawString(text,f,brush,new RectangleF(20,y,Width-40,height));
    }
    protected override void OnPaint(PaintEventArgs e){
        base.OnPaint(e);var g=e.Graphics;var m=Obj(state,"metric");var muted=Color.FromArgb(157,173,191);
        bool caution=Txt(m,"status")=="caution";Color accent=caution?Color.FromArgb(245,184,70):Color.FromArgb(85,204,209);
        if(Txt(state,"size")=="compact"){
            using(var f=new Font("Segoe UI",10,FontStyle.Bold))using(var b=new SolidBrush(ForeColor))using(var sf=new StringFormat()){
                sf.Trimming=StringTrimming.EllipsisCharacter;sf.FormatFlags=StringFormatFlags.NoWrap;
                g.DrawString(Txt(m,"label")+"   ·   "+Txt(state,"corner"),f,b,new RectangleF(16,12,Width-32,24),sf);
            }
            var compactScale=Obj(m,"scale");double v;bool known=Double.TryParse(Txt(compactScale,"fraction"),out v);
            for(int i=0;i<32;i++){
                float w=(Width-32)/32f;double edge=Math.Abs((i+.5)/32-.5);
                Color c=edge>.32?Color.FromArgb(150,43,52):edge>.16?Color.FromArgb(148,127,43):Color.FromArgb(32,126,64);
                if(known&&i==(int)Math.Min(31,Math.Max(0,v*32)))c=Color.FromArgb(244,246,250);
                using(var b=new SolidBrush(c))g.FillRectangle(b,new RectangleF(16+i*w,43,w-2,14));
            }
            using(var f=new Font("Segoe UI",8))using(var b=new SolidBrush(muted))using(var sf=new StringFormat()){
                string left=Txt(compactScale,"left");
                string right=Txt(compactScale,"right");
                g.DrawString(left,f,b,new RectangleF(16,67,Width/2-16,20));sf.Alignment=StringAlignment.Far;
                g.DrawString(right,f,b,new RectangleF(Width/2,67,Width/2-16,20),sf);
            }
            using(var f=new Font("Segoe UI",11,FontStyle.Bold))using(var b=new SolidBrush(Txt(m,"feedback_tone")=="good"?Color.FromArgb(96,221,135):Txt(m,"feedback_tone")=="caution"?Color.FromArgb(245,184,70):ForeColor))using(var sf=new StringFormat()){
                sf.Alignment=StringAlignment.Center;g.DrawString(Txt(m,"feedback"),f,b,new RectangleF(12,85,Width-24,24),sf);
            }
            return;
        }
        Label(g,"PADDOCK   /   "+Txt(m,"label").ToUpperInvariant(),16,10,accent,FontStyle.Bold,22);
        Label(g,Txt(state,"corner"),48,21,ForeColor,FontStyle.Bold,40);
        string value=Txt(m,"value");if(value=="")value="Waiting for evidence";else value+=" "+Txt(m,"unit");
        Label(g,value,94,value.Length>22?15:22,ForeColor,FontStyle.Bold,44);
        var scale=Obj(m,"scale");double fraction;
        bool hasScale=Double.TryParse(Txt(scale,"fraction"),out fraction);
        for(int i=0;i<28;i++){
            float w=(Width-40)/28f;var r=new RectangleF(20+i*w,151,w-3,23);
            double edge=Math.Abs((i+.5)/28-.5);
            Color c=edge>.32?Color.FromArgb(150,43,52):edge>.16?Color.FromArgb(148,127,43):Color.FromArgb(32,126,64);
            if(hasScale&&i==(int)Math.Min(27,Math.Max(0,fraction*28)))c=Color.FromArgb(244,246,250);
            using(var b=new SolidBrush(c))g.FillRectangle(b,r);
        }
        Label(g,hasScale?Txt(scale,"left")+"     →     "+Txt(scale,"right"):"Measurement • no optimal target",183,9,muted,FontStyle.Regular,24);
        Label(g,Txt(m,"detail"),216,10,muted,FontStyle.Regular,Height-260);
        Label(g,(Yes(state,"provisional")?"Live / incomplete corner":"Completed corner")+"   •   Lap "+Txt(state,"lap"),Height-37,9,accent,FontStyle.Regular,24);
    }
    void RefreshState(){try{
        if(parent!=null&&parent.HasExited){timer.Stop();Application.ExitThread();return;}
        var d=json.Deserialize<Dictionary<string,object>>(File.ReadAllText(path));double expiry;
        Double.TryParse(Txt(d,"expires_utc"),out expiry);uint pid;GetWindowThreadProcessId(GetForegroundWindow(),out pid);
        string name=pid==0?"":Process.GetProcessById((int)pid).ProcessName;
        bool game=name.Equals("AMS2AVX",StringComparison.OrdinalIgnoreCase)||name.Equals("AMS2",StringComparison.OrdinalIgnoreCase);
        if(!Yes(d,"enabled")||!Yes(d,"visible")||!game||expiry<=(DateTime.UtcNow-new DateTime(1970,1,1)).TotalSeconds){Hide();return;}
        Apply(d);if(!Visible)Show();
    }catch{Hide();}}
    protected override void OnFormClosed(FormClosedEventArgs e){timer.Stop();timer.Dispose();if(parent!=null)parent.Dispose();base.OnFormClosed(e);Application.ExitThread();}
    [STAThread]static int Main(string[] args){try{
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        if(args.Length==3&&args[0]=="--render"){
            using(var f=new SkillPanel(args[1],0)){
                f.timer.Stop();f.Apply(f.json.Deserialize<Dictionary<string,object>>(File.ReadAllText(args[1])));f.CreateControl();
                using(var b=new Bitmap(f.Width,f.Height)){f.DrawToBitmap(b,new Rectangle(0,0,b.Width,b.Height));b.Save(args[2]);}
                File.WriteAllText(args[2]+".labels.json",f.json.Serialize(new {metric=Obj(f.state,"metric"),corner=Txt(f.state,"corner"),no_activation=f.ShowWithoutActivation,width=f.Width,height=f.Height}));
            }return 0;
        }
        if(args.Length!=2)return 2;
        using(var f=new SkillPanel(args[0],Int32.Parse(args[1])))Application.Run(new ApplicationContext());return 0;
    }catch{return 1;}}
}
