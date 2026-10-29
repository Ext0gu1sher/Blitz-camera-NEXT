// Native window management only; camera operations stay in the existing service.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using Forms = System.Windows.Forms;

namespace BlitzCamera {
  public static class AppIcon {
    public static readonly System.Drawing.Icon Drawing;
    public static readonly ImageSource Image;
    static AppIcon(){
      var assembly=typeof(AppIcon).Assembly;
      using(var stream=assembly.GetManifestResourceStream("BlitzCamera.Icon")){
        Drawing=new System.Drawing.Icon(stream,32,32);
      }
      using(var stream=assembly.GetManifestResourceStream("BlitzCamera.Icon")){
        var decoder=new IconBitmapDecoder(stream,BitmapCreateOptions.PreservePixelFormat,BitmapCacheOption.OnLoad);
        var frame=decoder.Frames.OrderByDescending(f=>f.PixelWidth).First();frame.Freeze();Image=frame;
      }
    }
  }

  public static class Native {
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct Point { public int X, Y; }
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern IntPtr GetShellWindow();
    [DllImport("user32.dll")] public static extern bool AllowSetForegroundWindow(uint processId);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr h, int command);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h,StringBuilder name,int size);
    [DllImport("user32.dll")] public static extern IntPtr GetAncestor(IntPtr h, uint flags);
    public delegate bool EnumWindowProc(IntPtr h,IntPtr param);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowProc callback,IntPtr param);
    public delegate void WinEventProc(IntPtr hook, uint ev, IntPtr h, int obj, int child, uint thread, uint time);
    [DllImport("user32.dll")] public static extern IntPtr SetWinEventHook(uint first, uint last, IntPtr module, WinEventProc callback, uint process, uint thread, uint flags);
    [DllImport("user32.dll")] public static extern bool UnhookWinEvent(IntPtr hook);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out Rect r);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out Rect r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref Point p);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int command);
    [DllImport("user32.dll")] public static extern int GetWindowLong(IntPtr h, int index);
    [DllImport("user32.dll")] public static extern int SetWindowLong(IntPtr h, int index, int value);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int z, uint flags);
    [DllImport("user32.dll")] public static extern bool RegisterHotKey(IntPtr h, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] public static extern bool UnregisterHotKey(IntPtr h, int id);
    [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
    [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool ReleaseCapture();
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out Point p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
    [DllImport("user32.dll")] public static extern IntPtr SetCursor(IntPtr cursor);
    [DllImport("user32.dll")] public static extern bool GetClipCursor(out Rect rect);
    [DllImport("user32.dll")] public static extern bool GetCursorInfo(ref CursorInfo info);
    [DllImport("user32.dll")] public static extern bool ClipCursor(ref Rect rect);
    [DllImport("user32.dll")] public static extern bool RegisterRawInputDevices(RawInputDevice[] devices,uint count,uint size);
    [DllImport("user32.dll")] public static extern uint GetRawInputData(IntPtr input,uint command,out RawMouseInput data,ref uint size,uint headerSize);
    [StructLayout(LayoutKind.Sequential)] public struct RawInputDevice { public ushort Page,Usage;public uint Flags;public IntPtr Target; }
    [StructLayout(LayoutKind.Sequential)] public struct RawHeader { public uint Type,Size;public IntPtr Device,WParam; }
    [StructLayout(LayoutKind.Explicit,Size=24)] public struct RawMouse {
      [FieldOffset(0)]public ushort Flags;[FieldOffset(4)]public uint Buttons;
      [FieldOffset(12)]public int X;[FieldOffset(16)]public int Y;
    }
    [StructLayout(LayoutKind.Sequential)] public struct RawMouseInput { public RawHeader Header;public RawMouse Mouse; }
    [StructLayout(LayoutKind.Sequential)] public struct CursorInfo { public int Size,Flags;public IntPtr Cursor;public Point Position; }
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, int msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll")] public static extern IntPtr MonitorFromWindow(IntPtr h, int flags);
    [DllImport("user32.dll")] public static extern IntPtr MonitorFromRect(ref Rect r, uint flags);
    [DllImport("shcore.dll")] public static extern int GetDpiForMonitor(IntPtr h, int type, out uint x, out uint y);
    [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern bool GetMonitorInfo(IntPtr h, ref MONITORINFO info);
    [StructLayout(LayoutKind.Sequential)] public struct MinMaxInfo { public Point ptReserved; public Point ptMaxSize; public Point ptMaxPosition; public Point ptMinTrackSize; public Point ptMaxTrackSize; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)] public struct MONITORINFO { public int cbSize; public Rect rcMonitor; public Rect rcWork; public int dwFlags; }
  }

  public class Host {
    public static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    public readonly string Root, Url;
    public readonly Dictionary<string, PanelWindow> Panels = new Dictionary<string, PanelWindow>();
    public Dictionary<string, object> Layout = new Dictionary<string, object>();
    public const double ConnectionW=830,ConnectionH=100,ConnectionSettingsH=138,TelemetryH=294,CaptureH=160,KeyframesH=640;
    public CoreWebView2Environment Environment;
    public bool Hidden;
    public readonly bool StartWorkbench, Smoke;
    public WorkbenchWindow Workbench;
    public int Opacity = 80;
    public string HideKey = "F9";
    public string CaptureKey = "F8";
    public bool HideHotkeyRegistered,CaptureHotkeyRegistered,GameMinimized,GameInactive;
    public bool GameFeatures;
    Forms.ToolStripItem overlayMenu,layoutMenu;
    public bool AutoHidden {get{return GameMinimized||GameInactive;}}
    public IntPtr Game;
    public Native.Rect Area;
    HwndSource hotkeyWindow;
    IntPtr foregroundHook,locationHook;
    Native.WinEventProc foregroundCallback,locationCallback;
    Forms.NotifyIcon tray;
    DispatcherTimer timer,followTimer;
    bool placementQueued;
    int ticks;
    bool shuttingDown;
    public bool Dragging;
    bool workbenchRequested;
    bool capturePending;
    bool capturingShortcut;
    readonly List<string> warnings = new List<string>();
    readonly string layoutFile;

    public Host(string url, string root, bool workbench) {
      Root=root; Url=url; layoutFile=Path.Combine(root,"output/overlay-layout.json");
      StartWorkbench=workbench;Hidden=workbench;Smoke=System.Environment.GetEnvironmentVariable("BLITZCAM_DESKTOP_SMOKE")=="1";
      try {
        if(File.Exists(layoutFile)) Layout=Json.Deserialize<Dictionary<string,object>>(File.ReadAllText(layoutFile));
        if(Layout.ContainsKey("opacity")) Opacity=Math.Max(45,Math.Min(95,Convert.ToInt32(Layout["opacity"])));
        if(Layout.ContainsKey("hide_key")) HideKey=ValidKey(Convert.ToString(Layout["hide_key"]));
        if(Layout.ContainsKey("capture_key")) CaptureKey=ValidKey(Convert.ToString(Layout["capture_key"]));
        if(CaptureKey==HideKey)CaptureKey=HideKey=="F8"?"F9":"F8";
      } catch { Layout=new Dictionary<string,object>(); }
    }
    public async void Start() {
      try {
        if(!Smoke){
        hotkeyWindow=new HwndSource(new HwndSourceParameters("Blitz Camera hotkeys") {ParentWindow=new IntPtr(-3),WindowStyle=0});
        hotkeyWindow.AddHook(Hotkey);RegisterKeys(HideKey,CaptureKey);
        foregroundCallback=delegate {Application.Current.Dispatcher.BeginInvoke(new Action(delegate {if(!shuttingDown)RefreshVisibility(false);}));};
        foregroundHook=Native.SetWinEventHook(3,3,IntPtr.Zero,foregroundCallback,0,0,0);
        tray=new Forms.NotifyIcon {Icon=AppIcon.Drawing,Text="Blitz Camera",Visible=true};
        var menu=new Forms.ContextMenuStrip();
        overlayMenu=menu.Items.Add("显示 / 隐藏悬浮窗",null,delegate {ToggleOverlay();});overlayMenu.Visible=GameFeatures;
        menu.Items.Add("打开完整工作台",null,delegate {OpenWorkbench();});
        layoutMenu=menu.Items.Add("重置窗口布局",null,delegate {ResetLayout();});layoutMenu.Visible=GameFeatures;
        menu.Items.Add("退出 Blitz Camera",null,delegate {if(Workbench!=null)Workbench.Close();else Shutdown();});
        tray.ContextMenuStrip=menu;tray.DoubleClick+=delegate {Reveal();};
        if(warnings.Count>0)NotifyError(string.Join("；",warnings.ToArray()));
        }
        var browserOptions=new CoreWebView2EnvironmentOptions("--autoplay-policy=no-user-gesture-required");
        Environment=await CoreWebView2Environment.CreateAsync(null,Path.Combine(Root,"output/overlay-webview"),browserOptions);
        Panels.Add("connection",new PanelWindow(this,"connection","BLITZ CAMERA · 连接回放",ConnectionW,ConnectionH,ConnectionSettingsH));
        Panels.Add("telemetry",new PanelWindow(this,"telemetry","实时数据",272,TelemetryH));
        Panels.Add("capture",new PanelWindow(this,"capture","记录属性关键帧",272,CaptureH));
        Panels.Add("keyframes",new PanelWindow(this,"keyframes","轨迹预览 · 播放",328,KeyframesH));
        try{foreach(var k in (System.Collections.IEnumerable)Layout["collapsed"]){var kind=Convert.ToString(k);if(Panels.ContainsKey(kind))Panels[kind].ToggleCollapsed();}}catch{}
        followTimer=new DispatcherTimer(DispatcherPriority.Render){Interval=TimeSpan.FromMilliseconds(16)};
        followTimer.Tick+=delegate{RefreshPlacement();};
        if(!Smoke&&GameFeatures)FindGame();GetArea();RefreshVisibility(false);PositionAll();
        if(StartWorkbench||workbenchRequested||!GameFeatures)OpenWorkbench();
        timer=new DispatcherTimer {Interval=TimeSpan.FromMilliseconds(250)};
        timer.Tick+=delegate {
          if(++ticks%8==0&&!Smoke&&GameFeatures)FindGame();RefreshPlacement();
          if(!Smoke)RefreshVisibility(false);if(ticks%8==0)WriteStatus();
        };
        timer.Start();RefreshVisibility(false);WriteStatus();
      } catch(Exception e) {
        File.WriteAllText(Path.Combine(Root,"output/overlay-error.txt"),e.ToString());
        MessageBox.Show("悬浮窗启动失败："+e.Message+"\n详情见 output/overlay-error.txt","Blitz Camera");Shutdown();
      }
    }
    public static string ValidKey(string key) {
      if(new[]{"F7","F8","F9","F10","F11","F12"}.Contains(key))key="Ctrl+Alt+"+key;
      if(string.IsNullOrEmpty(key))throw new ArgumentException("全局快捷键不能为空。");
      var parts=key.Split('+');string code=parts.Last();var mods=parts.Take(parts.Length-1).ToArray();
      if(!mods.SequenceEqual(new[]{"Ctrl","Alt","Shift"}.Where(m=>mods.Contains(m)))||(!mods.Contains("Ctrl")&&!mods.Contains("Alt")))throw new ArgumentException("全局快捷键需包含 Ctrl 或 Alt。");
      KeyCode(code);
      if(code=="Tab"||code=="F12"||(mods.Contains("Alt")&&code=="F4")||(mods.Contains("Ctrl")&&!mods.Contains("Alt")&&new[]{"KeyS","KeyZ","KeyY","KeyA","KeyC","KeyV","KeyX","KeyR","KeyL","KeyW","KeyT","KeyN","KeyP","KeyF"}.Contains(code)))throw new ArgumentException("此按键保留给通用操作，请换一个。");
      return key;
    }
    public static uint KeyCode(string code){
      if(code.Length==4&&code.StartsWith("Key")&&code[3]>='A'&&code[3]<='Z')return code[3];
      if(code.Length==6&&code.StartsWith("Digit")&&code[5]>='0'&&code[5]<='9')return code[5];
      if(code.Length==7&&code.StartsWith("Numpad")&&code[6]>='0'&&code[6]<='9')return (uint)(96+code[6]-'0');
      int f;if(code.StartsWith("F")&&int.TryParse(code.Substring(1),out f)&&f>=1&&f<=12)return (uint)(111+f);
      var codes=new Dictionary<string,uint>{{"Tab",9},{"ArrowLeft",37},{"ArrowUp",38},{"ArrowRight",39},{"ArrowDown",40},{"Home",36},{"End",35},{"PageUp",33},{"PageDown",34},{"Insert",45},{"Backquote",192},{"Minus",189},{"Equal",187},{"BracketLeft",219},{"BracketRight",221},{"Backslash",220},{"Semicolon",186},{"Quote",222},{"Comma",188},{"Period",190},{"Slash",191}};
      uint vk;if(codes.TryGetValue(code,out vk))return vk;throw new ArgumentException("不支持的快捷键。");
    }
    static uint KeyModifiers(string key){uint mods=0;if(key.Contains("Ctrl+"))mods|=2;if(key.Contains("Alt+"))mods|=1;if(key.Contains("Shift+"))mods|=4;return mods;}
    public static bool MatchesKey(string chord,KeyEventArgs e){
      if(string.IsNullOrEmpty(chord))return false;
      try{uint mods=0;var m=Keyboard.Modifiers;if((m&ModifierKeys.Control)!=0)mods|=2;if((m&ModifierKeys.Alt)!=0)mods|=1;if((m&ModifierKeys.Shift)!=0)mods|=4;if((m&ModifierKeys.Windows)!=0)return false;
        return mods==KeyModifiers(chord)&&(uint)KeyInterop.VirtualKeyFromKey(e.Key==Key.System?e.SystemKey:e.Key)==KeyCode(chord.Split('+').Last());
      }catch{return false;}
    }
    public static string KeyLabel(string key){return key.Replace("Key","").Replace("Digit","").Replace("Numpad","小键盘 ");}
    bool RegisterKey(int id,string key){key=ValidKey(key);return Native.RegisterHotKey(hotkeyWindow.Handle,id,0x4000|KeyModifiers(key),KeyCode(key.Split('+').Last()));}
    void UnregisterKeys(){Native.UnregisterHotKey(hotkeyWindow.Handle,1);Native.UnregisterHotKey(hotkeyWindow.Handle,2);}
    void UpdateKeyWarnings(){
      warnings.Clear();
      if(!HideHotkeyRegistered)warnings.Add(KeyLabel(ValidKey(HideKey))+" 显示/隐藏快捷键被占用，请在设置中换键；仍可从托盘恢复窗口。");
      if(!CaptureHotkeyRegistered)warnings.Add(KeyLabel(ValidKey(CaptureKey))+" 打关键帧快捷键被占用，请在设置中换键。");
    }
    bool RegisterKeys(string hide,string capture) {
      hide=ValidKey(hide);capture=ValidKey(capture);
      if(hide==capture)throw new ArgumentException("显示/隐藏与打关键帧快捷键不能相同。");
      if(Smoke||hotkeyWindow==null||!GameFeatures){HideKey=hide;CaptureKey=capture;return true;}
      string oldHide=HideKey,oldCapture=CaptureKey;
      UnregisterKeys();
      bool hideOk=RegisterKey(1,hide),captureOk=RegisterKey(2,capture);
      if(hideOk&&captureOk){HideKey=hide;CaptureKey=capture;HideHotkeyRegistered=CaptureHotkeyRegistered=true;warnings.Clear();return true;}
      // Restore both previous assignments, including any key that was already
      // unavailable at startup. A failed edit never silently changes one key.
      UnregisterKeys();
      HideHotkeyRegistered=RegisterKey(1,oldHide);CaptureHotkeyRegistered=RegisterKey(2,oldCapture);UpdateKeyWarnings();
      string error="快捷键设置未生效："+string.Join("、",new[]{hideOk?null:KeyLabel(hide),captureOk?null:KeyLabel(capture)}.Where(k=>k!=null))+" 已被占用，请换键。";
      if(!warnings.Contains(error))warnings.Add(error);return false;
    }
    public void ApplySettings(Dictionary<string,object> m,string source="connection"){
      if(m.ContainsKey("hideKey")||m.ContainsKey("captureKey")){
        if(!RegisterKeys(m.ContainsKey("hideKey")?Convert.ToString(m["hideKey"]):HideKey,m.ContainsKey("captureKey")?Convert.ToString(m["captureKey"]):CaptureKey))
          SendFeedback(source,new{type="host-error",message=warnings.Last()});
      }
      if(m.ContainsKey("opacity"))Opacity=Math.Max(45,Math.Min(95,Convert.ToInt32(m["opacity"])));
      foreach(var p in Panels.Values)p.UpdateOpacity();SaveLayout();Broadcast(Status());WriteStatus();
    }
    public void SetShortcutCapture(bool active){
      if(shuttingDown){capturingShortcut=false;return;}
      if(active==capturingShortcut)return;capturingShortcut=active;
      if(Smoke||hotkeyWindow==null)return;
      if(active)UnregisterKeys();
      else{RegisterKeys(HideKey,CaptureKey);Broadcast(Status());WriteStatus();}
    }
    IntPtr Hotkey(IntPtr h,int msg,IntPtr w,IntPtr l,ref bool handled) {
      if(msg==0x312){if(GameFeatures&&!capturingShortcut){if(w.ToInt32()==1)ToggleOverlay();else if(w.ToInt32()==2)CaptureKeyframe();}handled=true;}return IntPtr.Zero;
    }
    public void Broadcast(object value){foreach(var p in Panels.Values)p.Send(value);if(Workbench!=null)Workbench.Send(value);}
    public bool SendFeedback(string target,object value){
      if(target=="workbench"&&Workbench!=null){Workbench.Send(value);return true;}
      PanelWindow panel;if(target!=null&&Panels.TryGetValue(target,out panel)){panel.Send(value);return true;}
      return false;
    }
    public string FeedbackTarget(IntPtr foreground){
      foreach(var p in Panels.Values)if(IsForegroundWindow(p.Handle,foreground))return p.Kind;
      if(Workbench!=null&&IsForegroundWindow(new WindowInteropHelper(Workbench).Handle,foreground))return "workbench";
      return "capture";
    }
    static bool IsForegroundWindow(IntPtr window,IntPtr foreground){
      return window!=IntPtr.Zero&&foreground!=IntPtr.Zero&&(window==foreground||Native.GetAncestor(foreground,3)==window);
    }
    void NotifyError(string message){if(tray!=null)tray.ShowBalloonTip(5000,"Blitz Camera",message,Forms.ToolTipIcon.Warning);}
    async void CaptureKeyframe(){await CaptureKeyframeAsync();}
    public async Task CaptureKeyframeAsync(string source=null){
      if(!GameFeatures)return;
      if(capturePending||shuttingDown)return;capturePending=true;
      string target=source??FeedbackTarget(Native.GetForegroundWindow());
      try{
        // Commit the current editor draft and playhead before choosing the
        // capture time. The service remains the sole camera-operation owner.
        if(Workbench!=null)await Workbench.FlushEditorAsync();
        await Task.Run((Action)delegate{
          var request=(HttpWebRequest)WebRequest.Create(Url+"api/capture/hotkey");
          request.Method="POST";request.ContentType="application/json";request.ContentLength=2;
          request.Timeout=15000;request.ReadWriteTimeout=15000;request.Proxy=null;request.AllowAutoRedirect=false;
          using(var body=request.GetRequestStream()){body.WriteByte((byte)'{');body.WriteByte((byte)'}');}
          try{using(var response=request.GetResponse()){} }
          catch(WebException error){
            if(error.Response!=null)using(var response=error.Response)using(var reader=new StreamReader(response.GetResponseStream())){
              var result=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(reader.ReadToEnd());
              if(result!=null&&result.ContainsKey("error"))throw new InvalidOperationException(Convert.ToString(result["error"]));
            }
            throw;
          }
        });
        if(!shuttingDown)SendFeedback(target,new{type="host-action",action="capture",ok=true,message="已记录全部七项属性关键帧。"});
      }catch(Exception error){if(!shuttingDown&&!SendFeedback(target,new{type="host-error",message=error.Message}))NotifyError("打关键帧失败："+error.Message);}
      finally{capturePending=false;}
    }
    void FindGame() {
      IntPtr found=IntPtr.Zero;
      foreach(var p in Process.GetProcessesByName("wotblitz")){
        try{if(p.MainWindowHandle!=IntPtr.Zero){found=p.MainWindowHandle;break;}}catch{}finally{p.Dispose();}
      }
      TrackGameWindow(found);
    }
    internal void TrackGameWindow(IntPtr window){
      if(Game==window)return;
      if(locationHook!=IntPtr.Zero){Native.UnhookWinEvent(locationHook);locationHook=IntPtr.Zero;}
      Game=window;
      if(Game!=IntPtr.Zero){
        uint pid;Native.GetWindowThreadProcessId(Game,out pid);
        locationCallback=delegate(IntPtr hook,uint ev,IntPtr hwnd,int obj,int child,uint thread,uint time){
          if(hwnd!=Game||obj!=0||child!=0||shuttingDown||Hidden||AutoHidden||placementQueued)return;
          placementQueued=true;
          Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Render,new Action(delegate{
            placementQueued=false;if(!shuttingDown)RefreshPlacement();
          }));
        };
        // Out-of-context notifications stay in this UI thread; no game hook or injection.
        if(pid!=0)locationHook=Native.SetWinEventHook(0x800B,0x800B,IntPtr.Zero,locationCallback,pid,0,0);
      }
      RefreshPlacement();
    }
    void RefreshPlacement(){
      var before=Area;GetArea();
      if(before.Left!=Area.Left||before.Top!=Area.Top||before.Right!=Area.Right||before.Bottom!=Area.Bottom)PositionAll();
    }
    void GetArea() {
      if(Game!=IntPtr.Zero&&Native.IsIconic(Game)&&Area.Right>Area.Left)return;
      Native.Rect r;var point=new Native.Point();
      if(Game!=IntPtr.Zero&&!Native.IsIconic(Game)&&Native.GetClientRect(Game,out r)&&r.Right>100&&Native.ClientToScreen(Game,ref point))
        Area=new Native.Rect {Left=point.X,Top=point.Y,Right=point.X+r.Right,Bottom=point.Y+r.Bottom};
      else {
        // Use the same monitor until reset, rather than following the mouse between monitors.
        var s=Forms.Screen.FromPoint(new System.Drawing.Point(Area.Left+10,Area.Top+10)).WorkingArea;
        Area=new Native.Rect {Left=s.Left,Top=s.Top,Right=s.Right,Bottom=s.Bottom};
      }
    }
    public PanelLayout.Anchor AnchorFor(string kind){
      try{return PanelLayout.ReadAnchor(kind,(Dictionary<string,object>)((Dictionary<string,object>)Layout["anchors"])[kind]);}
      catch{return PanelLayout.DefaultAnchor(kind);}
    }
    public void StoreAnchor(string kind,PanelLayout.Anchor a){
      Dictionary<string,object> all;object raw;
      if(Layout.TryGetValue("anchors",out raw)&&raw is Dictionary<string,object>)all=(Dictionary<string,object>)raw;
      else Layout["anchors"]=all=new Dictionary<string,object>();
      all[kind]=PanelLayout.WriteAnchor(a);
    }
    public void DetachDependants(string kind){
      foreach(var p in Panels.Values){
        if(p.Kind==kind||p.Handle==IntPtr.Zero)continue;
        var a=AnchorFor(p.Kind);if(a.HRef!=kind&&a.VRef!=kind)continue;
        Native.Rect r;if(!Native.GetWindowRect(p.Handle,out r))continue;
        PanelLayout.StripRef(a,kind,r,Area,Math.Max(.5,p.Scale));StoreAnchor(p.Kind,a);
      }
    }
    public void DockFromRect(PanelWindow p){
      Native.Rect r;if(!Native.GetWindowRect(p.Handle,out r))return;
      var others=new Dictionary<string,Native.Rect>();var anchors=new Dictionary<string,PanelLayout.Anchor>();
      foreach(var q in Panels.Values)if(q.Kind!=p.Kind&&q.Handle!=IntPtr.Zero&&q.Shown){Native.Rect o;if(Native.GetWindowRect(q.Handle,out o)){others[q.Kind]=o;anchors[q.Kind]=AnchorFor(q.Kind);}}
      StoreAnchor(p.Kind,PanelLayout.Derive(r,Area,Math.Max(.5,p.Scale),others,anchors,p.Kind));
      SaveLayout();PositionAll();WriteStatus();
    }
    public double AreaScale(){
      try{var r=Area;uint x,y;if(Native.GetDpiForMonitor(Native.MonitorFromRect(ref r,2),0,out x,out y)==0&&x>0)return x/96.0;}catch{}
      return 1;
    }
    public void PositionAll(){
      if(Dragging)return;
      if(Smoke&&Game==IntPtr.Zero){foreach(var p in Panels.Values)if(p.Handle!=IntPtr.Zero)Native.SetWindowPos(p.Handle,IntPtr.Zero,-32000,-32000,0,0,0x15);return;}
      double scale=Math.Max(.5,AreaScale());
      var anchors=new Dictionary<string,PanelLayout.Anchor>();var sizes=new Dictionary<string,System.Drawing.Size>();
      foreach(var p in Panels.Values){
        if(p.Handle==IntPtr.Zero)continue;
        sizes[p.Kind]=new System.Drawing.Size((int)Math.Min((p.Kind=="connection"?ConnectionW:p.Width)*scale,Area.Right-Area.Left-24),(int)Math.Min(p.Height*scale,Area.Bottom-Area.Top-24));
        anchors[p.Kind]=AnchorFor(p.Kind);
      }
      var rects=PanelLayout.ResolveAll(anchors,sizes,Area,scale);
      foreach(var p in Panels.Values){Native.Rect q;if(p.Handle!=IntPtr.Zero&&rects.TryGetValue(p.Kind,out q))Native.SetWindowPos(p.Handle,IntPtr.Zero,q.Left,q.Top,q.Right-q.Left,q.Bottom-q.Top,0x14);}
    }
    public bool ForegroundAllowsOverlay(IntPtr foreground){
      if(Game==IntPtr.Zero||IsForegroundWindow(Game,foreground))return true;
      return Panels.Values.Any(p=>p.WantsVisible&&p.Shown&&IsForegroundWindow(p.Handle,foreground));
    }
    public void RefreshVisibility(bool force) {RefreshVisibility(force,Native.GetForegroundWindow());}
    public void RefreshVisibility(bool force,IntPtr foreground) {
      // Automatic suspension is separate from the user's hide preference, so
      // restoring the game cannot reveal panels the user explicitly hid.
      bool previouslyHidden=AutoHidden;
      GameMinimized=Game!=IntPtr.Zero&&Native.IsIconic(Game);
      GameInactive=Game!=IntPtr.Zero&&!ForegroundAllowsOverlay(foreground);
      bool show=GameFeatures&&!Hidden&&!AutoHidden,created=false;
      if(show)RefreshPlacement();
      foreach(var p in Panels.Values)created|=p.SetShown(show,!force&&!GameMinimized&&Game!=IntPtr.Zero);
      if(created)PositionAll();
      if(show)RestoreOverlayOrder();
      if(followTimer!=null){if(show&&Game!=IntPtr.Zero)followTimer.Start();else followTimer.Stop();}
      if(previouslyHidden!=AutoHidden&&Workbench!=null)Workbench.Send(Status());
    }
    void RestoreOverlayOrder(){
      // WS_EX_TOPMOST only identifies a band: a topmost game can still cover
      // an individual panel in that band. Check actual order once per refresh,
      // and leave already-correct windows alone so polling cannot churn Z order.
      if(Smoke||Game==IntPtr.Zero||(Native.GetWindowLong(Game,-20)&0x8)==0)return;
      var covered=new HashSet<IntPtr>(Panels.Values.Where(p=>p.WantsVisible&&p.Shown).Select(p=>p.Handle));
      if(covered.Count==0)return;
      bool foundGame=false;
      Native.EnumWindows(delegate(IntPtr window,IntPtr param){
        if(window==Game){foundGame=true;return false;}
        covered.Remove(window);return covered.Count>0;
      },IntPtr.Zero);
      if(!foundGame)return;
      foreach(var p in Panels.Values)if(covered.Contains(p.Handle))
        Native.SetWindowPos(p.Handle,new IntPtr(-1),0,0,0,0,0x13); // NOSIZE | NOMOVE | NOACTIVATE
    }
    public void SetGameFeatures(bool enabled){
      if(GameFeatures==enabled)return;GameFeatures=enabled;
      if(overlayMenu!=null)overlayMenu.Visible=enabled;if(layoutMenu!=null)layoutMenu.Visible=enabled;
      if(enabled)RegisterKeys(HideKey,CaptureKey);
      else {if(hotkeyWindow!=null)UnregisterKeys();HideHotkeyRegistered=CaptureHotkeyRegistered=false;warnings.Clear();Hidden=true;}
      RefreshVisibility(true);Broadcast(Status());WriteStatus();
    }
    public void SetOverlayHidden(bool value){Hidden=!GameFeatures||value;RefreshVisibility(true);if(!Hidden)PositionAll();Broadcast(Status());WriteStatus();}
    public void ToggleOverlay(){SetOverlayHidden(!Hidden);}
    public void Reveal(){if(GameFeatures)SetOverlayHidden(false);else OpenWorkbench();}
    public void ResetLayout(){Layout.Remove("positions");Layout.Remove("anchors");Layout.Remove("collapsed");foreach(var p in Panels.Values)p.Expand();PositionAll();SaveLayout();}
    public void SaveCollapsed(){Layout["collapsed"]=Panels.Values.Where(p=>p.Collapsed).Select(p=>p.Kind).ToArray();SaveLayout();}
    public Dictionary<string,object> Status(){return new Dictionary<string,object>{{"type","host-state"},{"projectFolder",true},{"hidden",Hidden},{"autoHidden",AutoHidden},{"gameMinimized",GameMinimized},{"gameInactive",GameInactive},{"opacity",Opacity},{"hideKey",HideKey},{"captureKey",CaptureKey},{"hideHotkeyRegistered",HideHotkeyRegistered},{"captureHotkeyRegistered",CaptureHotkeyRegistered},{"gameFound",Game!=IntPtr.Zero},{"warnings",warnings.ToArray()}};}
    public void SaveLayout() {
      Layout["opacity"]=Opacity;Layout["hide_key"]=HideKey;Layout["capture_key"]=CaptureKey;Layout.Remove("pass_key");Layout.Remove("positions");
      var temp=layoutFile+".tmp";File.WriteAllText(temp,Json.Serialize(Layout));if(File.Exists(layoutFile))File.Replace(temp,layoutFile,null);else File.Move(temp,layoutFile);
    }
    public void WriteStatus() {
      try{
        var s=Status();s["pid"]=Process.GetCurrentProcess().Id;s["url"]=Url;
        s["windows"]=Panels.Values.Select(p=>new{panel=p.Kind,visible=p.Shown,width=p.ActualWidth,height=p.ActualHeight,collapsed=p.Collapsed,hwnd=p.Handle.ToInt64(),transparent=(Native.GetWindowLong(p.Handle,-20)&0x80000)!=0,ready=p.Ready}).ToArray();
        s["workbench"]=Workbench==null?null:new{visible=Workbench.IsVisible,ready=Workbench.Ready,dirty=Workbench.Dirty,mouseCaptured=Workbench.MouseCaptured,mouseCapture=Workbench.MouseCaptureState,hwnd=new WindowInteropHelper(Workbench).Handle.ToInt64()};
        File.WriteAllText(Path.Combine(Root,"output/overlay-status.json"),Json.Serialize(s));
      }catch{}
    }
    public void OpenWorkbench(string source="connection") {
      if(Environment==null){workbenchRequested=true;return;}
      try {
        if(Workbench==null){Workbench=new WorkbenchWindow(this);Workbench.Show();}
        else {if(Workbench.WindowState==WindowState.Minimized)Workbench.WindowState=WindowState.Normal;Workbench.Show();if(!Smoke)Workbench.Activate();}
        SendFeedback(source,new{type="host-action",action="workbench",ok=true});
      } catch(Exception e) {
        File.WriteAllText(Path.Combine(Root,"output/overlay-workbench-error.txt"),e.ToString());
        SendFeedback(source,new{type="host-error",message="打开桌面工作台失败："+e.Message});
      }
    }
    public void ConfigureWeb(CoreWebView2 web) {
      web.Settings.AreDefaultContextMenusEnabled=false;web.Settings.AreDevToolsEnabled=false;web.Settings.IsStatusBarEnabled=false;
      web.Settings.IsZoomControlEnabled=false;web.Settings.AreBrowserAcceleratorKeysEnabled=false;web.Settings.AreHostObjectsAllowed=false;
      web.NavigationStarting+=delegate(object s,CoreWebView2NavigationStartingEventArgs e){if(!SameOrigin(e.Uri))e.Cancel=true;};
      web.NewWindowRequested+=delegate(object s,CoreWebView2NewWindowRequestedEventArgs e){e.Handled=true;};
      web.PermissionRequested+=delegate(object s,CoreWebView2PermissionRequestedEventArgs e){e.State=CoreWebView2PermissionState.Deny;};
    }
    public bool SameOrigin(string source){Uri p;return Uri.TryCreate(source,UriKind.Absolute,out p)&&p.GetLeftPart(UriPartial.Authority)==new Uri(Url).GetLeftPart(UriPartial.Authority);}
    public void Message(PanelWindow panel,CoreWebView2WebMessageReceivedEventArgs e) {
      if(!SameOrigin(e.Source))return;
      try{
        var m=Json.Deserialize<Dictionary<string,object>>(e.WebMessageAsJson);
        switch(Convert.ToString(m["command"])){
          case "ready":panel.SendStatus();break;
          case "summary":panel.SetSummary(Convert.ToString(m["text"]));return;
          case "workbench":OpenWorkbench(panel.Kind);break;
          case "hide":SetOverlayHidden(true);break;
          case "reset":ResetLayout();break;
          case "settings":
            if(panel.Kind!="connection")return;
            ApplySettings(m,panel.Kind);break;
          case "settings-height":panel.SetSettingsOpen(Convert.ToBoolean(m["open"]));break;
        }
        Broadcast(Status());WriteStatus();
      }catch(Exception error){panel.Send(new{type="host-error",message=error.Message});}
    }
    public void Shutdown(){
      if(shuttingDown)return;shuttingDown=true;if(timer!=null)timer.Stop();if(followTimer!=null)followTimer.Stop();
      if(foregroundHook!=IntPtr.Zero){Native.UnhookWinEvent(foregroundHook);foregroundHook=IntPtr.Zero;}
      if(locationHook!=IntPtr.Zero){Native.UnhookWinEvent(locationHook);locationHook=IntPtr.Zero;}
      if(hotkeyWindow!=null){UnregisterKeys();hotkeyWindow.Dispose();}
      if(tray!=null){tray.Visible=false;tray.Dispose();}if(Workbench!=null){Workbench.AllowClose=true;Workbench.Web.Dispose();Workbench.Close();Workbench=null;}foreach(var p in Panels.Values){p.Web.Dispose();p.Close();}Application.Current.Shutdown();
    }
  }

  // Composition WebView2 reports pointer lock without capturing the desktop cursor.
  // Own relative input only during flight; every exit path restores the cursor.
  public sealed class FlightMouse {
    readonly Window window;
    readonly WebView2CompositionControl web;
    Native.Point returnPoint;
    Native.Rect previousClip;
    Cursor previousCursor;
    int request,dx,dy;
    bool motionQueued,suppressMouseUp;
    public bool Active { get;private set; }
    public object Status(){
      Native.Rect clip;var cursor=new Native.CursorInfo{Size=Marshal.SizeOf(typeof(Native.CursorInfo))};
      bool clipped=Native.GetClipCursor(out clip)&&clip.Right-clip.Left==1&&clip.Bottom-clip.Top==1;
      bool hidden=Native.GetCursorInfo(ref cursor)&&(cursor.Flags&1)==0;
      return new{active=Active,clipped=clipped,hidden=hidden};
    }
    string exitKey="Tab",exitMouse="Mouse0";
    public FlightMouse(Window owner,WebView2CompositionControl view){
      window=owner;web=view;
      window.Deactivated+=delegate{Stop();};
      window.LocationChanged+=delegate{Stop();};
      window.SizeChanged+=delegate{Stop();};
      window.Closed+=delegate{Stop();};
      web.PreviewMouseMove+=delegate(object s,MouseEventArgs e){if(Active)e.Handled=true;};
      web.PreviewMouseDown+=delegate(object s,MouseButtonEventArgs e){
        if(!Active)return;e.Handled=true;suppressMouseUp=true;
        string button=e.ChangedButton==MouseButton.Left?"Mouse0":e.ChangedButton==MouseButton.Middle?"Mouse1":e.ChangedButton==MouseButton.Right?"Mouse2":e.ChangedButton==MouseButton.XButton1?"Mouse3":"Mouse4";
        if(button==exitMouse)Stop();
      };
      web.PreviewMouseUp+=delegate(object s,MouseButtonEventArgs e){if(Active||suppressMouseUp){e.Handled=true;suppressMouseUp=false;}};
      web.PreviewMouseWheel+=delegate(object s,MouseWheelEventArgs e){if(!Active)return;e.Handled=true;Send(new{type="flight-wheel",id=request,delta=-e.Delta});};
      web.PreviewKeyDown+=delegate(object s,KeyEventArgs e){if(Active&&(e.Key==Key.Escape||Host.MatchesKey(exitKey,e))){e.Handled=true;Stop();}};
    }
    void Send(object message){try{web.CoreWebView2.PostWebMessageAsJson(Host.Json.Serialize(message));}catch{}}
    public void Start(int id,double x,double y,string key="Tab",string mouse="Mouse0"){
      Stop();request=id;exitKey=key;exitMouse=mouse;
      if(id<=0||!window.IsActive||!web.IsVisible||double.IsNaN(x)||double.IsInfinity(x)||double.IsNaN(y)||double.IsInfinity(y)||x<0||y<0||x>=web.ActualWidth||y>=web.ActualHeight){Send(new{type="flight-state",id=request,active=false});return;}
      if(!Native.GetCursorPos(out returnPoint)||!Native.GetClipCursor(out previousClip)){Send(new{type="flight-state",id=request,active=false});return;}
      IntPtr hwnd=new WindowInteropHelper(window).Handle;
      // Composition hosting can focus a browser-owned child HWND; route raw input
      // explicitly to this window and unregister immediately on deactivation.
      var devices=new[]{new Native.RawInputDevice{Page=1,Usage=2,Flags=0x100,Target=hwnd}};
      if(!Native.RegisterRawInputDevices(devices,1,(uint)Marshal.SizeOf(typeof(Native.RawInputDevice)))){Send(new{type="flight-state",id=request,active=false});return;}
      var center=web.PointToScreen(new System.Windows.Point(x,y));
      var clip=new Native.Rect{Left=(int)center.X,Top=(int)center.Y,Right=(int)center.X+1,Bottom=(int)center.Y+1};
      Active=true;dx=dy=0;previousCursor=Mouse.OverrideCursor;Mouse.OverrideCursor=Cursors.None;Native.SetCursor(IntPtr.Zero);
      if(!Native.ClipCursor(ref clip)){Stop();return;}
      web.Focus();Send(new{type="flight-state",id=request,active=true});
    }
    public void Stop(int id=0){
      if(!Active||(id!=0&&id!=request))return;
      Active=false;dx=dy=0;
      Native.ClipCursor(ref previousClip);
      Native.RegisterRawInputDevices(new[]{new Native.RawInputDevice{Page=1,Usage=2,Flags=1}},1,(uint)Marshal.SizeOf(typeof(Native.RawInputDevice)));
      Mouse.OverrideCursor=previousCursor;
      if(window.IsActive)Native.SetCursorPos(returnPoint.X,returnPoint.Y);
      Send(new{type="flight-state",id=request,active=false});
    }
    public void Input(IntPtr input){
      if(!Active)return;
      uint size=(uint)Marshal.SizeOf(typeof(Native.RawMouseInput));Native.RawMouseInput raw;
      if(Native.GetRawInputData(input,0x10000003,out raw,ref size,(uint)Marshal.SizeOf(typeof(Native.RawHeader)))==uint.MaxValue||raw.Header.Type!=0||(raw.Mouse.Flags&1)!=0)return;
      dx+=raw.Mouse.X;dy+=raw.Mouse.Y;
      if(motionQueued||(dx==0&&dy==0))return;
      motionQueued=true;int id=request;
      window.Dispatcher.BeginInvoke(DispatcherPriority.Render,new Action(delegate{
        motionQueued=false;if(!Active||id!=request)return;
        int x=dx,y=dy;dx=dy=0;Send(new{type="flight-motion",id=request,dx=x,dy=y});
      }));
    }
  }

  public class WorkbenchWindow:Window {
    public readonly WebView2CompositionControl Web;
    public bool Ready,Dirty,AllowClose;
    public bool MouseCaptured {get{return flight.Active;}}
    public object MouseCaptureState {get{return flight.Status();}}
    bool exportCompleted;
    readonly Host host;
    readonly FlightMouse flight;
    bool initialized,closePending,openingProjectFolder;
    int closeRequest;
    int flushRequest;
    readonly Dictionary<int,TaskCompletionSource<bool>> editorFlushRequests=new Dictionary<int,TaskCompletionSource<bool>>();
    public WorkbenchWindow(Host owner){
      host=owner;Title="Blitz Camera NEXT · 完整工作台";Icon=AppIcon.Image;MinWidth=960;MinHeight=620;
      Width=Math.Min(1440,SystemParameters.WorkArea.Width-32);Height=Math.Min(920,SystemParameters.WorkArea.Height-32);
      WindowStartupLocation=WindowStartupLocation.CenterScreen;Background=new SolidColorBrush(Color.FromRgb(23,23,23));
      WindowStyle=WindowStyle.None;
      System.Windows.Shell.WindowChrome.SetWindowChrome(this,new System.Windows.Shell.WindowChrome{
        CaptionHeight=0,ResizeBorderThickness=new Thickness(6),GlassFrameThickness=new Thickness(0,0,0,1),
        CornerRadius=new CornerRadius(0),UseAeroCaptionButtons=false});
      if(host.Smoke){WindowStartupLocation=WindowStartupLocation.Manual;Left=-32000;Top=-32000;Opacity=0;ShowInTaskbar=false;ShowActivated=false;}
      var frame=new Border{Background=Background};
      // Composition WebView does not forward Explorer's OLE drops to the DOM.
      // Receive FileDrop at the WPF window, including every child hit target.
      AllowDrop=true;
      Web=new WebView2CompositionControl{MinWidth=64,MinHeight=64,AllowDrop=true,AllowExternalDrop=false,DefaultBackgroundColor=System.Drawing.Color.FromArgb(255,23,23,23)};frame.Child=Web;Content=frame;
      PreviewDragEnter+=ReplayDragOver;PreviewDragOver+=ReplayDragOver;
      PreviewDragLeave+=delegate(object s,DragEventArgs e){
        if(!e.Data.GetDataPresent(DataFormats.FileDrop))return;
        e.Handled=true;Send(new{type="replay-file-drag",phase="leave"});
      };
      PreviewDrop+=delegate(object s,DragEventArgs e){
        if(!e.Data.GetDataPresent(DataFormats.FileDrop))return;
        e.Handled=true;e.Effects=DragDropEffects.None;
        if(!Ready||closePending)return;
        try{
          var paths=e.Data.GetData(DataFormats.FileDrop) as string[];
          Send(new{type="replay-file-drag",phase="drop",paths=paths??new string[0]});
          e.Effects=e.AllowedEffects&DragDropEffects.Copy;
        }catch(Exception error){Send(new{type="replay-file-drag",phase="leave"});Send(new{type="host-error",message="读取拖入文件失败："+error.Message});}
      };
      flight=new FlightMouse(this,Web);
      Deactivated+=delegate{host.SetShortcutCapture(false);};
      Closed+=delegate{host.SetShortcutCapture(false);};
      StateChanged+=delegate{frame.Padding=WindowState==WindowState.Maximized?SystemParameters.WindowResizeBorderThickness:new Thickness(0);SendWindowState();};
      SourceInitialized+=delegate{
        HwndSource source=HwndSource.FromHwnd(new WindowInteropHelper(this).Handle);
        if(source!=null)source.AddHook(WorkbenchWndProc);
      };
      Closing+=delegate(object s,System.ComponentModel.CancelEventArgs e){
        flight.Stop();
        if(AllowClose)return;
        e.Cancel=true;
        if(closePending)return;
        if(!Ready||Web.CoreWebView2==null){FinishClose(!Dirty,"编辑器尚未就绪，无法完成自动保存。");return;}
        closePending=true;
        closeRequest++;
        Web.CoreWebView2.PostWebMessageAsJson(Host.Json.Serialize(new{type="flush-editor",id=closeRequest}));
        WaitForEditorFlush(closeRequest);
      };
      Loaded+=async delegate{
        if(initialized)return;initialized=true;
        try{
          await Web.EnsureCoreWebView2Async(host.Environment);host.ConfigureWeb(Web.CoreWebView2);
          Web.CoreWebView2.NavigationStarting+=delegate{flight.Stop();host.SetShortcutCapture(false);};
          Web.CoreWebView2.ProcessFailed+=delegate(object s,CoreWebView2ProcessFailedEventArgs e){
            flight.Stop();
            File.WriteAllText(Path.Combine(host.Root,"output/desktop-process-failed.json"),Host.Json.Serialize(new{kind=e.ProcessFailedKind.ToString(),reason=e.Reason.ToString(),exitCode=e.ExitCode,description=e.ProcessDescription}));
          };
          Web.CoreWebView2.DownloadStarting+=delegate(object s,CoreWebView2DownloadStartingEventArgs e){
            e.Handled=true;
            if(host.Smoke){e.ResultFilePath=Path.Combine(host.Root,"output/desktop-export.json");}
            else{
              var save=new Microsoft.Win32.SaveFileDialog{FileName=Path.GetFileName(e.ResultFilePath),Filter="JSON 项目 (*.json)|*.json|所有文件 (*.*)|*.*",DefaultExt=".json"};
              if(save.ShowDialog(this)!=true){e.Cancel=true;return;}e.ResultFilePath=save.FileName;
            }
            var operation=e.DownloadOperation;operation.StateChanged+=delegate{if(operation.State==CoreWebView2DownloadState.Completed)exportCompleted=true;};
          };
          Web.CoreWebView2.WebMessageReceived+=async delegate(object s,CoreWebView2WebMessageReceivedEventArgs e){
            if(!host.SameOrigin(e.Source))return;
            try{
              var m=Host.Json.Deserialize<Dictionary<string,object>>(e.WebMessageAsJson);
              var command=Convert.ToString(m["command"]);
              if(command=="ready")Send(host.Status());
              else if(command=="edition")host.SetGameFeatures(Convert.ToBoolean(m["enabled"]));
              else if(command=="replay-drop-path"){
                int id=Convert.ToInt32(m["id"]);
                try{
                  var objects=e.AdditionalObjects;
                  if(objects==null||objects.Count!=1)throw new InvalidOperationException("请每次拖入一个 .wotbreplay 回放文件。");
                  var file=objects[0] as CoreWebView2File;
                  string path=file==null?null:file.Path;
                  if(String.IsNullOrWhiteSpace(path)||!Path.IsPathRooted(path)||!String.Equals(Path.GetExtension(path),".wotbreplay",StringComparison.OrdinalIgnoreCase)||!File.Exists(path))
                    throw new InvalidOperationException("请选择有效的 .wotbreplay 回放文件。");
                  Send(new{type="replay-drop-path",id=id,path=path});
                }catch(Exception error){Send(new{type="replay-drop-path",id=id,error=error.Message});}
              }
              else if(command=="settings")host.ApplySettings(m,"workbench");
              else if(command=="open-project-folder"){
                int id=Convert.ToInt32(m["id"]);
                try{
                  await OpenProjectFolder(Convert.ToString(m["directory"]));
                  Send(new{type="project-folder-opened",id=id});
                }catch(Exception error){Send(new{type="project-folder-opened",id=id,error=error.Message});}
              }
              else if(command=="shortcut-capture")host.SetShortcutCapture(Convert.ToBoolean(m["active"]));
              else if(command=="dirty")Dirty=Convert.ToBoolean(m["value"]);
              else if(command=="editor-flushed"){
                int id=Convert.ToInt32(m["id"]);bool success=Convert.ToBoolean(m["success"]);
                string error=m.ContainsKey("error")?Convert.ToString(m["error"]):"编辑器自动保存未完成。";
                TaskCompletionSource<bool> pending;
                if(editorFlushRequests.TryGetValue(id,out pending)){
                  if(success)pending.TrySetResult(true);else pending.TrySetException(new InvalidOperationException(error));
                }else if(closePending&&id==closeRequest)FinishClose(success,error);
              }
              else if(command=="flight"){
                int id=Convert.ToInt32(m["id"]);
                if(Convert.ToString(m["action"])=="start")flight.Start(id,Convert.ToDouble(m["x"]),Convert.ToDouble(m["y"]),m.ContainsKey("exitKey")?Convert.ToString(m["exitKey"]):"Tab",m.ContainsKey("exitMouse")?Convert.ToString(m["exitMouse"]):"Mouse0");
                else flight.Stop(id);
              }
              else if(command=="window"){
                var action=Convert.ToString(m["action"]);
                if(action=="drag"){Native.ReleaseCapture();Native.SendMessage(new WindowInteropHelper(this).Handle,0xA1,new IntPtr(2),IntPtr.Zero);}
                else if(action=="minimize")WindowState=WindowState.Minimized;
                else if(action=="maximize")WindowState=WindowState==WindowState.Maximized?WindowState.Normal:WindowState.Maximized;
                else if(action=="close")Close();
              }
            }catch(Exception error){Send(new{type="host-error",message=error.Message});}
          };
          Web.CoreWebView2.NavigationCompleted+=async delegate(object s,CoreWebView2NavigationCompletedEventArgs e){
            Ready=e.IsSuccess;SendWindowState();Send(host.Status());host.WriteStatus();if(host.Smoke)await SmokeCheck();
          };
          Web.CoreWebView2.Navigate(host.Url);
        }catch(Exception e){File.WriteAllText(Path.Combine(host.Root,"output/desktop-error.txt"),e.ToString());if(!host.Smoke)MessageBox.Show(this,"桌面工作台启动失败："+e.Message,"Blitz Camera");host.Shutdown();}
      };
    }
    static object ShellMember(object value,string name,BindingFlags flags,params object[] args){
      return value.GetType().InvokeMember(name,flags,null,value,args);
    }
    static string FolderKey(string directory){
      return Path.GetFullPath(directory).TrimEnd(Path.DirectorySeparatorChar,Path.AltDirectorySeparatorChar);
    }
    static IntPtr FindProjectFolderWindow(string directory){
      object shell=null,windows=null;
      try{
        shell=Activator.CreateInstance(Type.GetTypeFromProgID("Shell.Application",true));
        windows=ShellMember(shell,"Windows",BindingFlags.InvokeMethod);
        int count=Convert.ToInt32(ShellMember(windows,"Count",BindingFlags.GetProperty));
        for(int i=0;i<count;i++){
          object window=null;
          try{
            window=ShellMember(windows,"Item",BindingFlags.InvokeMethod,i);
            if(window==null)continue;
            Uri location;
            if(!Uri.TryCreate(Convert.ToString(ShellMember(window,"LocationURL",BindingFlags.GetProperty)),UriKind.Absolute,out location)||!location.IsFile)continue;
            if(!String.Equals(FolderKey(location.LocalPath),FolderKey(directory),StringComparison.OrdinalIgnoreCase))continue;
            var hwnd=new IntPtr(Convert.ToInt64(ShellMember(window,"HWND",BindingFlags.GetProperty)));
            var name=new StringBuilder(64);Native.GetClassName(hwnd,name,name.Capacity);
            if(name.ToString()=="CabinetWClass"||name.ToString()=="ExploreWClass")return hwnd;
          }catch(COMException){}catch(TargetInvocationException){}catch(ArgumentException){}
          finally{if(window!=null&&Marshal.IsComObject(window))Marshal.ReleaseComObject(window);}
        }
        return IntPtr.Zero;
      }finally{
        if(windows!=null&&Marshal.IsComObject(windows))Marshal.ReleaseComObject(windows);
        if(shell!=null&&Marshal.IsComObject(shell))Marshal.ReleaseComObject(shell);
      }
    }
    static IntPtr ForegroundRoot(){
      IntPtr foreground=Native.GetForegroundWindow();
      return foreground==IntPtr.Zero?IntPtr.Zero:Native.GetAncestor(foreground,2);
    }
    public async Task OpenProjectFolder(string directory){
      if(String.IsNullOrWhiteSpace(directory)||!Path.IsPathRooted(directory)||!Directory.Exists(directory))
        throw new InvalidOperationException("文件夹不存在或暂时无法访问。");
      if(openingProjectFolder)throw new InvalidOperationException("正在打开文件夹，请稍候。");
      directory=Path.GetFullPath(directory);
      openingProjectFolder=true;
      IntPtr owner=new WindowInteropHelper(this).Handle;
      var report=new Dictionary<string,object>{{"time",DateTime.UtcNow.ToString("o")},{"directory",directory},{"host",typeof(Host).Assembly.Location},{"owner",owner.ToInt64()},{"foregroundBefore",ForegroundRoot().ToInt64()},{"success",false}};
      try{
        // The WebView may own the focused child. Keep foreground ownership in
        // this UI process before handing the user's click to Explorer.
        if(ForegroundRoot()==owner)Native.SetForegroundWindow(owner);
        IntPtr target=FindProjectFolderWindow(directory);
        report["reused"]=target!=IntPtr.Zero;
        if(target==IntPtr.Zero){
          uint shellPid;IntPtr shell=Native.GetShellWindow();
          if(shell!=IntPtr.Zero&&Native.GetWindowThreadProcessId(shell,out shellPid)!=0)
            Native.AllowSetForegroundWindow(shellPid);
          using(var opened=Process.Start(new ProcessStartInfo{FileName=directory,Verb="open",UseShellExecute=true,WindowStyle=ProcessWindowStyle.Normal})){}
          // ShellExecute can return before Explorer has registered its window.
          for(int i=0;i<40&&target==IntPtr.Zero;i++){
            await Task.Delay(150);target=FindProjectFolderWindow(directory);
          }
        }
        report["target"]=target.ToInt64();
        if(target==IntPtr.Zero)throw new InvalidOperationException("已请求打开文件夹，但未找到对应的资源管理器窗口，请重试。");
        report["restored"]=Native.IsIconic(target);
        for(int i=0;i<4;i++){
          IntPtr foreground=ForegroundRoot();
          if(foreground==target&&!Native.IsIconic(target)){report["success"]=true;return;}
          // Do not keep pulling focus back if the user switches to another app.
          if(foreground!=owner&&foreground!=target&&foreground!=IntPtr.Zero)break;
          uint targetPid;
          if(Native.GetWindowThreadProcessId(target,out targetPid)!=0)Native.AllowSetForegroundWindow(targetPid);
          if(Native.IsIconic(target))Native.ShowWindowAsync(target,9); // SW_RESTORE
          report["activationAccepted"]=Native.SetForegroundWindow(target);
          await Task.Delay(100);
        }
        if(ForegroundRoot()!=target||Native.IsIconic(target))
          throw new InvalidOperationException("文件夹已打开，但未能切到前台，请点击任务栏中的文件夹窗口。");
        report["success"]=true;
      }catch(Exception error){report["error"]=error.Message;throw;}
      finally{
        openingProjectFolder=false;report["foregroundAfter"]=ForegroundRoot().ToInt64();
        try{File.WriteAllText(Path.Combine(host.Root,"output/project-folder-open.json"),Host.Json.Serialize(report));}catch{}
      }
    }
    void ReplayDragOver(object sender,DragEventArgs e){
      if(!e.Data.GetDataPresent(DataFormats.FileDrop))return;
      e.Handled=true;e.Effects=Ready&&!closePending?e.AllowedEffects&DragDropEffects.Copy:DragDropEffects.None;
      if(Ready)Send(new{type="replay-file-drag",phase="over"});
    }
    public void Send(object value){try{if(Web.CoreWebView2!=null)Web.CoreWebView2.PostWebMessageAsJson(Host.Json.Serialize(value));}catch{}}
    public async Task FlushEditorAsync(){
      if(!Ready||Web.CoreWebView2==null)throw new InvalidOperationException("编辑器尚未就绪，请稍后再打关键帧。");
      int id=--flushRequest;
      var pending=new TaskCompletionSource<bool>();editorFlushRequests.Add(id,pending);
      try{
        Send(new{type="flush-editor",id=id});
        if(await Task.WhenAny(pending.Task,Task.Delay(15000))!=pending.Task)throw new TimeoutException("等待编辑器自动保存超时，未添加关键帧。");
        await pending.Task;
      }finally{editorFlushRequests.Remove(id);}
    }
    async void WaitForEditorFlush(int request){
      await Task.Delay(18000);
      if(closePending&&request==closeRequest)FinishClose(false,"等待自动保存超时。");
    }
    void FinishClose(bool saved,string error){
      closePending=false;
      if(!saved&&MessageBox.Show(this,"自动保存未完成："+error+"\n仍要退出？","Blitz Camera",MessageBoxButton.YesNo,MessageBoxImage.Question)!=MessageBoxResult.Yes)return;
      Dispatcher.BeginInvoke(new Action(host.Shutdown));
    }
    void SendWindowState(){
      try{if(Web!=null&&Web.CoreWebView2!=null)Web.CoreWebView2.PostWebMessageAsJson(Host.Json.Serialize(new Dictionary<string,object>{{"type","window-state"},{"maximized",WindowState==WindowState.Maximized}}));}catch{}
    }
    IntPtr WorkbenchWndProc(IntPtr hwnd,int msg,IntPtr wParam,IntPtr lParam,ref bool handled){
      if(msg==0xFF){flight.Input(lParam);return IntPtr.Zero;}
      if(msg==0x20&&flight.Active){Native.SetCursor(IntPtr.Zero);handled=true;return new IntPtr(1);}
      if(msg!=0x24)return IntPtr.Zero;
      IntPtr monitor=Native.MonitorFromWindow(hwnd,2);
      Native.MONITORINFO mi=new Native.MONITORINFO();
      mi.cbSize=Marshal.SizeOf(typeof(Native.MONITORINFO));
      if(!Native.GetMonitorInfo(monitor,ref mi))return IntPtr.Zero;
      Native.MinMaxInfo info=(Native.MinMaxInfo)Marshal.PtrToStructure(lParam,typeof(Native.MinMaxInfo));
      const int edge=7;
      info.ptMaxPosition.X=mi.rcWork.Left-mi.rcMonitor.Left-edge;
      info.ptMaxPosition.Y=mi.rcWork.Top-mi.rcMonitor.Top-edge;
      info.ptMaxSize.X=mi.rcWork.Right-mi.rcWork.Left+edge*2;
      info.ptMaxSize.Y=mi.rcWork.Bottom-mi.rcWork.Top+edge*2;
      Marshal.StructureToPtr(info,lParam,true);
      handled=true;
      return IntPtr.Zero;
    }
    async Task ClearFeedbackSmoke(){
      foreach(var p in host.Panels.Values)await p.Web.CoreWebView2.ExecuteScriptAsync("document.getElementById('toast').hidden=true");
      await Web.CoreWebView2.ExecuteScriptAsync("document.getElementById('toast').hidden=true");
    }
    async Task CheckFeedbackSmoke(string target,bool error){
      await Task.Delay(100);
      const string script="(()=>{const t=document.getElementById('toast');return !t.hidden&&t.classList.contains('error')===ERROR;})()";
      foreach(var p in host.Panels.Values){
        string shown=await p.Web.CoreWebView2.ExecuteScriptAsync(script.Replace("ERROR",error?"true":"false"));
        if((shown=="true")!=(p.Kind==target))throw new Exception("Feedback reached the wrong overlay: "+p.Kind);
        if(p.Kind!=target&&await p.Web.CoreWebView2.ExecuteScriptAsync("document.getElementById('toast').hidden")!="true")throw new Exception("Unrelated overlay displayed feedback: "+p.Kind);
      }
      if(await Web.CoreWebView2.ExecuteScriptAsync("document.getElementById('toast').hidden")!="true")throw new Exception("Overlay feedback leaked to the workbench");
    }
    async Task SettleOverlaySmoke(){
      for(int i=0;i<100&&host.Panels.Values.Any(p=>((UIElement)p.Content).HasAnimatedProperties);i++)await Task.Delay(20);
      if(host.Panels.Values.Any(p=>((UIElement)p.Content).HasAnimatedProperties))throw new Exception("Overlay fade did not finish");
    }
    async Task SmokeCheck(){
      string result="null";
      try{
        for(int i=0;i<300;i++){
          result=await Web.CoreWebView2.ExecuteScriptAsync("JSON.stringify({loaded:typeof state!=='undefined'&&state.loaded,startup:document.body.dataset.appReady==='true',version:document.title,timeline:!!document.getElementById('sequenceEditor'),mode:typeof state!=='undefined'?state.shootingMode:null,webview:!!window.chrome.webview,background:getComputedStyle(document.body).backgroundColor})");
          if(result.Contains("\\\"loaded\\\":true")&&result.Contains("\\\"startup\\\":true"))break;await Task.Delay(100);
        }
        // Allow the package harness to test duplicate launch against this host.
        await Task.Delay(1200);
        if(Environment.GetEnvironmentVariable("BLITZCAM_OVERLAY_SMOKE")=="1"){
          host.SetOverlayHidden(false);
          for(int i=0;i<300&&!host.Panels.Values.All(p=>p.Ready);i++)await Task.Delay(100);
          if(!host.Panels.Values.All(p=>p.Ready))throw new Exception("Overlay pages did not initialize");
          for(int i=0;i<3;i++){
            // Exercise the actual page bridge, then the shared tray/hotkey path.
            await host.Panels["connection"].Web.CoreWebView2.ExecuteScriptAsync("document.getElementById('hide').click()");
            await Task.Delay(150);
            if(!host.Hidden||host.Panels.Values.Any(p=>p.Shown)||!IsVisible||!Native.IsWindowVisible(new WindowInteropHelper(this).Handle))throw new Exception("Overlay hide affected workbench");
            string alive=await Web.CoreWebView2.ExecuteScriptAsync("state.loaded&&!!document.getElementById('sequenceEditor')");
            if(alive!="true")throw new Exception("Workbench lost editor on hide");
            host.ToggleOverlay();await Task.Delay(150);
            if(host.Hidden||host.Panels.Values.Any(p=>!p.Shown))throw new Exception("Overlay reveal failed");
            foreach(var p in host.Panels.Values)p.ToggleCollapsed();await Task.Delay(150);
            if(host.Panels.Values.Any(p=>!p.Collapsed||p.Web.ActualWidth<64||p.Web.ActualHeight<64))throw new Exception("Collapsed WebView has invalid capture size");
            foreach(var p in host.Panels.Values)p.Expand();await Task.Delay(150);
            host.Panels["connection"].SetSettingsOpen(true);await Task.Delay(100);host.Panels["connection"].SetSettingsOpen(false);
          }
          // An offscreen stand-in exercises actual Windows minimize state;
          // no game process or foreground desktop window is used by this test.
          var gameFixture=new Window{Width=1280,Height=900,Left=-32000,Top=-32000,ShowInTaskbar=false,ShowActivated=false,Opacity=0};
          try{
            gameFixture.Show();host.TrackGameWindow(new WindowInteropHelper(gameFixture).Handle);
            host.RefreshVisibility(false,host.Game);
            await SettleOverlaySmoke();
            if(host.AutoHidden||host.Panels.Values.Any(p=>!p.Shown))throw new Exception("Foreground game did not reveal overlay");
            // Move and resize the real stand-in HWND repeatedly. Each position must
            // be observed before the old 250 ms poll could catch up.
            var previousRects=new Dictionary<string,Native.Rect>();
            for(int i=0;i<12;i++){
              Native.SetWindowPos(host.Game,IntPtr.Zero,-31000+i*11,-31000+i*7,1280+Math.Max(0,i-5)*5,900+Math.Max(0,i-5)*3,0x14);
              Native.Rect client;Native.GetClientRect(host.Game,out client);var origin=new Native.Point();Native.ClientToScreen(host.Game,ref origin);
              var clock=Stopwatch.StartNew();
              while((host.Area.Left!=origin.X||host.Area.Top!=origin.Y||host.Area.Right!=origin.X+client.Right||host.Area.Bottom!=origin.Y+client.Bottom)&&clock.ElapsedMilliseconds<120)await Task.Delay(5);
              if(host.Area.Left!=origin.X||host.Area.Top!=origin.Y||host.Area.Right!=origin.X+client.Right||host.Area.Bottom!=origin.Y+client.Bottom)throw new Exception("Overlay following fell back to slow polling");
              foreach(var p in host.Panels.Values){
                Native.Rect r;Native.GetWindowRect(p.Handle,out r);
                if(i>0&&i<6&&(r.Left-previousRects[p.Kind].Left!=11||r.Top-previousRects[p.Kind].Top!=7))throw new Exception("A panel did not follow the game translation: "+p.Kind);
                if(r.Left<host.Area.Left||r.Top<host.Area.Top||r.Right>host.Area.Right||r.Bottom>host.Area.Bottom)throw new Exception("Resized game left a panel outside its client area: "+p.Kind);
                previousRects[p.Kind]=r;
              }
            }
            foreach(var p in host.Panels.Values){host.RefreshVisibility(false,p.Handle);if(host.AutoHidden||host.Panels.Values.Any(q=>!q.Shown))throw new Exception("Interacting with a panel hid the overlay");}
            if(host.FeedbackTarget(host.Panels["telemetry"].Handle)!="telemetry"||host.FeedbackTarget(new WindowInteropHelper(this).Handle)!="workbench"||host.FeedbackTarget(host.Game)!="capture")throw new Exception("Hotkey feedback did not follow its initiating window");
            string layoutBefore=Host.Json.Serialize(host.Layout);
            host.RefreshVisibility(false,new WindowInteropHelper(this).Handle);
            if(host.Panels.Values.Any(p=>!p.Shown||p.IsHitTestVisible||!((UIElement)p.Content).HasAnimatedProperties||(Native.GetWindowLong(p.Handle,-20)&0x20)==0))throw new Exception("Focus loss did not start a click-through fade");
            await SettleOverlaySmoke();
            if(!host.GameInactive||!host.AutoHidden||host.Hidden||host.Panels.Values.Any(p=>p.Shown||p.Topmost)||!IsVisible)throw new Exception("Background game left an overlay over the workbench");
            host.RefreshVisibility(false,host.Game);
            if(host.Panels.Values.Any(p=>!p.Shown||!p.IsHitTestVisible||!((UIElement)p.Content).HasAnimatedProperties||(Native.GetWindowLong(p.Handle,-20)&0x20)!=0))throw new Exception("Focus return did not restore an interactive fade-in");
            await SettleOverlaySmoke();
            if(host.GameInactive||host.AutoHidden||host.Panels.Values.Any(p=>!p.Shown)||Host.Json.Serialize(host.Layout)!=layoutBefore)throw new Exception("Foreground restore changed overlay visibility or layout");
            // A fast Alt-Tab reversal must cancel the obsolete completion callback.
            host.RefreshVisibility(false,new WindowInteropHelper(this).Handle);await Task.Delay(40);
            host.RefreshVisibility(false,host.Game);await SettleOverlaySmoke();await Task.Delay(160);
            if(host.AutoHidden||host.Panels.Values.Any(p=>!p.Shown||((UIElement)p.Content).Opacity!=1||!p.IsHitTestVisible))throw new Exception("Rapid focus reversal left an old fade hiding the overlay");
            foreach(var panel in host.Panels.Values){
              // Simulate a single HWND losing visibility while its requested
              // state stays visible, then recover through the normal refresh.
              Native.ShowWindow(panel.Handle,0);
              host.RefreshVisibility(false,host.Game);await SettleOverlaySmoke();
              if(host.Panels.Values.Any(p=>!p.Shown||((UIElement)p.Content).Opacity!=1||!p.IsHitTestVisible))throw new Exception("Single-panel visibility drift was not repaired: "+panel.Kind);
              ((UIElement)panel.Content).Opacity=0;
              Native.SetWindowLong(panel.Handle,-20,Native.GetWindowLong(panel.Handle,-20)|0x20);
              host.RefreshVisibility(false,panel.Handle);await SettleOverlaySmoke();
              if(!panel.Shown||((UIElement)panel.Content).Opacity!=1||(Native.GetWindowLong(panel.Handle,-20)&0x20)!=0)throw new Exception("Single-panel opacity/input drift was not repaired: "+panel.Kind);
              host.RefreshVisibility(false,new WindowInteropHelper(this).Handle);await Task.Delay(25);
              host.RefreshVisibility(false,host.Game);await Task.Delay(25);
              Native.ShowWindow(panel.Handle,0);
              host.RefreshVisibility(false,host.Game);await SettleOverlaySmoke();
              if(host.Panels.Values.Any(p=>!p.Shown||((UIElement)p.Content).Opacity!=1||!p.IsHitTestVisible))throw new Exception("Interrupted panel fade did not recover: "+panel.Kind);
            }
            Native.ShowWindow(host.Game,6);host.RefreshVisibility(false,host.Game);
            if(!host.AutoHidden||host.Hidden||host.Panels.Values.Any(p=>p.Shown)||!IsVisible)throw new Exception("Game minimization did not suspend only the overlay");
            Native.ShowWindow(host.Game,4);host.RefreshVisibility(false,host.Game);
            await SettleOverlaySmoke();
            if(host.AutoHidden||host.Hidden||host.Panels.Values.Any(p=>!p.Shown))throw new Exception("Game restore did not restore overlay");
            host.SetOverlayHidden(true);Native.ShowWindow(host.Game,6);host.RefreshVisibility(false,host.Game);
            Native.ShowWindow(host.Game,4);host.RefreshVisibility(false,host.Game);
            if(host.AutoHidden||!host.Hidden||host.Panels.Values.Any(p=>p.Shown)||!IsVisible)throw new Exception("Game restore overrode manual hide");
          }finally{host.TrackGameWindow(IntPtr.Zero);gameFixture.Close();host.RefreshVisibility(false);}
          string hideBefore=host.HideKey,captureBefore=host.CaptureKey;bool conflictRejected=false;
          try{host.ApplySettings(new Dictionary<string,object>{{"hideKey",hideBefore},{"captureKey",hideBefore}});}catch(ArgumentException){conflictRejected=true;}
          if(!conflictRejected||host.HideKey!=hideBefore||host.CaptureKey!=captureBefore)throw new Exception("Conflicting key assignment was not rejected atomically");
          host.SetOverlayHidden(true);
          File.WriteAllText(Path.Combine(host.Root,"output/desktop-overlay-smoke.json"),Host.Json.Serialize(new{hidePreservedWorkbench=true,revealPassed=true,collapsePassed=true,positiveCaptureSize=true,minimizeHides=true,restoreReveals=true,backgroundHides=true,foregroundRestores=true,fastMoveAndResizeFollow=true,focusFadeOut=true,focusFadeIn=true,fadeClickThrough=true,rapidFocusReversal=true,singlePanelRecovery=true,interruptedPanelFadeRecovery=true,panelInteractionVisible=true,layoutPreserved=true,manualHidePreserved=true,keyConflictRejected=true,cycles=3}));
        }
        if(Environment.GetEnvironmentVariable("BLITZCAM_CAPTURE_SMOKE")=="1"){
          host.SetOverlayHidden(true);
          await ClearFeedbackSmoke();
          await Web.CoreWebView2.ExecuteScriptAsync("showHome(false);seek(2);setDirty(true)");
          await host.CaptureKeyframeAsync("capture");
          if(!host.Hidden||host.Panels.Values.Any(p=>p.Shown)||Dirty)throw new Exception("Hidden-overlay capture did not flush the editor and preserve visibility");
          await CheckFeedbackSmoke("capture",false);
          await ClearFeedbackSmoke();
          await Web.CoreWebView2.ExecuteScriptAsync("window.__smokeFlush=window.BlitzFlushEditorSession;window.BlitzFlushEditorSession=async()=>{throw Error('synthetic flush failure')};seek(3)");
          await host.CaptureKeyframeAsync("telemetry");
          await CheckFeedbackSmoke("telemetry",true);
          await Web.CoreWebView2.ExecuteScriptAsync("window.BlitzFlushEditorSession=window.__smokeFlush;delete window.__smokeFlush");
          File.WriteAllText(Path.Combine(host.Root,"output/desktop-capture-smoke.json"),Host.Json.Serialize(new{hiddenOverlayCapture=true,editorFlushed=true,flushFailureCancelsCapture=true,successOnlyAtOrigin=true,errorOnlyAtOrigin=true}));
        }
        if(Environment.GetEnvironmentVariable("BLITZCAM_PREVIEW_SMOKE")=="1"){
          // Native startup now opens the project home page. Enter the editor so
          // its preview has a visible drawing area before checking the scene.
          await Web.CoreWebView2.ExecuteScriptAsync("showHome(false)");
          await Task.Delay(250);
          string preview="null";
          for(int i=0;i<1800;i++){
            preview=await Web.CoreWebView2.ExecuteScriptAsync("JSON.stringify({status:typeof replayPreviewPane!=='undefined'?replayPreviewPane?.status:null,message:document.getElementById('previewStatus')?.textContent})");
            if(preview.Contains("\\\"status\\\":\\\"ready\\\"")||preview.Contains("\\\"status\\\":\\\"error\\\""))break;
            await Task.Delay(100);
          }
          string diagnostics=await Web.CoreWebView2.ExecuteScriptAsync("JSON.stringify((()=>{if(!window.BlitzReplayPreviewDiagnostics)return {ready:false};seek(60);const a=BlitzReplayPreviewDiagnostics();seek(75);seek(60);const b=BlitzReplayPreviewDiagnostics();replayPreviewPane.setView('camera');return {ready:a.state==='ready',backwardStable:JSON.stringify(a.visible)===JSON.stringify(b.visible),diagnostics:BlitzReplayPreviewDiagnostics()};})())");
          File.WriteAllText(Path.Combine(host.Root,"output/desktop-preview-smoke.json"),Host.Json.Serialize(new{status=preview,result=diagnostics}));
        }
        await Web.CoreWebView2.ExecuteScriptAsync("setDirty(true)");await Task.Delay(100);bool dirtySeen=Dirty;
        await Web.CoreWebView2.ExecuteScriptAsync("setDirty(false)");await Task.Delay(100);
        await Web.CoreWebView2.ExecuteScriptAsync("(()=>{const a=document.createElement('a');a.href='/api/export';a.download='blitz-camera-project.json';document.body.append(a);a.click();a.remove();})()");
        for(int i=0;i<100&&!exportCompleted;i++)await Task.Delay(100);
        File.WriteAllText(Path.Combine(host.Root,"output/desktop-actions.json"),Host.Json.Serialize(new{dirtySeen=dirtySeen,dirtyCleared=!Dirty,exportCompleted=exportCompleted,applicationIcon=Icon!=null&&AppIcon.Drawing!=null}));
        File.WriteAllText(Path.Combine(host.Root,"output/desktop-smoke.json"),result);
      }catch(Exception e){File.WriteAllText(Path.Combine(host.Root,"output/desktop-smoke-error.txt"),e.ToString());}
      Close();
    }
  }

  // Area-independent docking: anchors survive area size/origin changes and
  // let panels reference each other's resolved edges.
  public static class PanelLayout {
    public const double DockMargin=8,DockGap=8,SnapThreshold=16;
    public sealed class Anchor{public string H="free",V="free",HRef,VRef;public double X=.5,Y=.1;}
    public static Anchor DefaultAnchor(string kind){
      switch(kind){
        case "connection":return new Anchor{H="center",V="top"};
        case "telemetry":return new Anchor{H="left",V="middle"};
        case "capture":return new Anchor{H="left",V="below",VRef="telemetry"};
        case "keyframes":return new Anchor{H="right",V="middle"};
        default:return new Anchor();
      }
    }
    public static Anchor ReadAnchor(string kind,IDictionary<string,object> m){
      var a=DefaultAnchor(kind);
      if(m.ContainsKey("h"))a.H=Convert.ToString(m["h"]);
      if(m.ContainsKey("v"))a.V=Convert.ToString(m["v"]);
      if(m.ContainsKey("x"))a.X=Convert.ToDouble(m["x"]);
      if(m.ContainsKey("y"))a.Y=Convert.ToDouble(m["y"]);
      var single=m.ContainsKey("ref")?Convert.ToString(m["ref"]):null;
      var hr=m.ContainsKey("href")?Convert.ToString(m["href"]):null;
      var vr=m.ContainsKey("vref")?Convert.ToString(m["vref"]):null;
      bool hu=a.H=="after"||a.H=="before",vu=a.V=="below"||a.V=="above";
      a.HRef=hu?(hr??single):null;a.VRef=vu?(vr??single):null;
      if(a.HRef=="")a.HRef=null;if(a.VRef=="")a.VRef=null;
      if(!new[]{"left","right","center","after","before","free"}.Contains(a.H))a.H="free";
      if(!new[]{"top","middle","bottom","below","above","free"}.Contains(a.V))a.V="free";
      return a;
    }
    public static Dictionary<string,object> WriteAnchor(Anchor a){
      var d=new Dictionary<string,object>{{"h",a.H},{"x",a.X},{"v",a.V},{"y",a.Y}};
      if(a.HRef!=null&&a.VRef!=null){d["href"]=a.HRef;d["vref"]=a.VRef;}
      else if(a.HRef!=null)d["ref"]=a.HRef;else if(a.VRef!=null)d["ref"]=a.VRef;
      return d;
    }
    static int FreeX(Native.Rect area,int w,double m,double x){double span=area.Right-area.Left-w-2*m;if(span<1)span=1;return area.Left+(int)Math.Round(m+Math.Max(0,Math.Min(1,x))*span);}
    static int FreeY(Native.Rect area,int h,double m,double y){double span=area.Bottom-area.Top-h-2*m;if(span<1)span=1;return area.Top+(int)Math.Round(m+Math.Max(0,Math.Min(1,y))*span);}
    public static double RatioX(Native.Rect r,Native.Rect area,double scale){double m=DockMargin*scale,span=area.Right-area.Left-(r.Right-r.Left)-2*m;if(span<1)span=1;return Math.Max(0,Math.Min(1,(r.Left-area.Left-m)/span));}
    public static double RatioY(Native.Rect r,Native.Rect area,double scale){double m=DockMargin*scale,span=area.Bottom-area.Top-(r.Bottom-r.Top)-2*m;if(span<1)span=1;return Math.Max(0,Math.Min(1,(r.Top-area.Top-m)/span));}
    public static int AnchorX(Anchor a,Native.Rect area,int w,double scale,IDictionary<string,Native.Rect> placed){
      double m=DockMargin*scale,g=DockGap*scale;Native.Rect o;
      switch(a.H){
        case "left":return area.Left+(int)Math.Round(m);
        case "right":return area.Right-(int)Math.Round(m)-w;
        case "center":return area.Left+(area.Right-area.Left-w)/2;
        case "after":return a.HRef!=null&&placed.TryGetValue(a.HRef,out o)?o.Right+(int)Math.Round(g):FreeX(area,w,m,a.X);
        case "before":return a.HRef!=null&&placed.TryGetValue(a.HRef,out o)?o.Left-(int)Math.Round(g)-w:FreeX(area,w,m,a.X);
        default:return FreeX(area,w,m,a.X);
      }
    }
    public static int AnchorY(Anchor a,Native.Rect area,int h,double scale,IDictionary<string,Native.Rect> placed){
      double m=DockMargin*scale,g=DockGap*scale;Native.Rect o;
      switch(a.V){
        case "top":return area.Top+(int)Math.Round(m);
        case "bottom":return area.Bottom-(int)Math.Round(m)-h;
        case "below":return a.VRef!=null&&placed.TryGetValue(a.VRef,out o)?o.Bottom+(int)Math.Round(g):FreeY(area,h,m,a.Y);
        case "above":return a.VRef!=null&&placed.TryGetValue(a.VRef,out o)?o.Top-(int)Math.Round(g)-h:FreeY(area,h,m,a.Y);
        default:return FreeY(area,h,m,a.Y);
      }
    }
    static int StackHeight(string kind,IDictionary<string,Anchor> anchors,IDictionary<string,System.Drawing.Size> sizes,int gap,HashSet<string> visited){
      if(!visited.Add(kind))return 0;
      System.Drawing.Size s;if(!sizes.TryGetValue(kind,out s))return 0;
      int best=0;
      foreach(var kv in anchors)if(kv.Value.V=="below"&&kv.Value.VRef==kind){int c=StackHeight(kv.Key,anchors,sizes,gap,visited);if(gap+c>best)best=gap+c;}
      return s.Height+best;
    }
    public static Dictionary<string,Native.Rect> ResolveAll(IDictionary<string,Anchor> anchors,IDictionary<string,System.Drawing.Size> sizes,Native.Rect area,double scale){
      var placed=new Dictionary<string,Native.Rect>();
      foreach(var k in anchors.Keys)ResolveInto(k,anchors,sizes,area,scale,placed,new HashSet<string>());
      return placed;
    }
    static void ResolveInto(string kind,IDictionary<string,Anchor> anchors,IDictionary<string,System.Drawing.Size> sizes,Native.Rect area,double scale,Dictionary<string,Native.Rect> placed,HashSet<string> stack){
      if(placed.ContainsKey(kind)||!anchors.ContainsKey(kind)||!sizes.ContainsKey(kind))return;
      var a=anchors[kind];stack.Add(kind);
      foreach(var rf in new[]{a.HRef,a.VRef})
        if(rf!=null&&!placed.ContainsKey(rf)&&!stack.Contains(rf))ResolveInto(rf,anchors,sizes,area,scale,placed,stack);
      var s=sizes[kind];
      int x=AnchorX(a,area,s.Width,scale,placed);
      int y=a.V=="middle"?area.Top+(area.Bottom-area.Top-StackHeight(kind,anchors,sizes,(int)Math.Round(DockGap*scale),new HashSet<string>()))/2:AnchorY(a,area,s.Height,scale,placed);
      int cx=Math.Max(area.Left,Math.Min(x,area.Right-s.Width)),cy=Math.Max(area.Top,Math.Min(y,area.Bottom-s.Height));
      stack.Remove(kind);placed[kind]=new Native.Rect{Left=cx,Top=cy,Right=cx+s.Width,Bottom=cy+s.Height};
    }
    static int Snap1(int cur,double t,IEnumerable<double> targets){
      int best=cur;double bd=t+1;
      foreach(var c in targets){double d=Math.Abs(c-cur);if(d<=t&&d<bd){bd=d;best=(int)Math.Round(c);}}
      return best;
    }
    public static Native.Rect SnapMoving(Native.Rect r,Native.Rect area,double scale,IDictionary<string,Native.Rect> others){
      double m=DockMargin*scale,g=DockGap*scale,t=SnapThreshold*scale;
      int w=r.Right-r.Left,h=r.Bottom-r.Top;
      var xs=new List<double>{area.Left+m,area.Right-m-w,area.Left+(area.Right-area.Left-w)/2.0};
      var ys=new List<double>{area.Top+m,area.Bottom-m-h,area.Top+(area.Bottom-area.Top-h)/2.0};
      foreach(var kv in others){
        var o=kv.Value;
        if(r.Top<o.Bottom&&o.Top<r.Bottom||Math.Max(o.Top-r.Bottom,r.Top-o.Bottom)<=2*t){xs.Add(o.Right+g);xs.Add(o.Left-g-w);xs.Add(o.Left);xs.Add(o.Right-w);}
        if(r.Left<o.Right&&o.Left<r.Right||Math.Max(o.Left-r.Right,r.Left-o.Right)<=2*t){ys.Add(o.Bottom+g);ys.Add(o.Top-g-h);ys.Add(o.Top);ys.Add(o.Bottom-h);}
      }
      int x=Snap1(r.Left,t,xs),y=Snap1(r.Top,t,ys);
      return new Native.Rect{Left=x,Top=y,Right=x+w,Bottom=y+h};
    }
    static bool DependsOn(string self,string candidate,IDictionary<string,Anchor> anchors){
      var q=new Queue<string>();q.Enqueue(candidate);
      while(q.Count>0){var c=q.Dequeue();if(c==self)return true;Anchor a;if(anchors.TryGetValue(c,out a)){if(a.HRef!=null)q.Enqueue(a.HRef);if(a.VRef!=null)q.Enqueue(a.VRef);}}
      return false;
    }
    public static Anchor Derive(Native.Rect r,Native.Rect area,double scale,IDictionary<string,Native.Rect> others,IDictionary<string,Anchor> anchors,string self){
      double m=DockMargin*scale,g=DockGap*scale;
      int w=r.Right-r.Left,h=r.Bottom-r.Top;
      var a=new Anchor{X=RatioX(r,area,scale),Y=RatioY(r,area,scale)};
      if(Math.Abs(r.Left-(area.Left+m))<=1)a.H="left";
      else if(Math.Abs(r.Right-(area.Right-m))<=1)a.H="right";
      else if(Math.Abs(r.Left-(area.Left+(area.Right-area.Left-w)/2))<=1)a.H="center";
      else{
        foreach(var kv in others){
          var o=kv.Value;
          if(Math.Abs(r.Left-(o.Right+g))<=1){a.H="after";a.HRef=kv.Key;break;}
          if(Math.Abs(r.Right-(o.Left-g))<=1){a.H="before";a.HRef=kv.Key;break;}
        }
        if(a.H=="free")foreach(var kv in others){
          var o=kv.Value;Anchor oa=anchors.ContainsKey(kv.Key)?anchors[kv.Key]:DefaultAnchor(kv.Key);
          if(Math.Abs(r.Left-o.Left)<=1&&oa.H=="left"){a.H="left";break;}
          if(Math.Abs(r.Right-o.Right)<=1&&oa.H=="right"){a.H="right";break;}
        }
      }
      if(Math.Abs(r.Top-(area.Top+m))<=1)a.V="top";
      else if(Math.Abs(r.Bottom-(area.Bottom-m))<=1)a.V="bottom";
      else if(Math.Abs(r.Top-(area.Top+(area.Bottom-area.Top-h)/2))<=1)a.V="middle";
      else{
        foreach(var kv in others){
          var o=kv.Value;
          if(Math.Abs(r.Top-(o.Bottom+g))<=1){a.V="below";a.VRef=kv.Key;break;}
          if(Math.Abs(r.Bottom-(o.Top-g))<=1){a.V="above";a.VRef=kv.Key;break;}
        }
        if(a.V=="free")foreach(var kv in others){
          var o=kv.Value;Anchor oa=anchors.ContainsKey(kv.Key)?anchors[kv.Key]:DefaultAnchor(kv.Key);
          if(Math.Abs(r.Top-o.Top)<=1&&oa.V=="top"){a.V="top";break;}
          if(Math.Abs(r.Bottom-o.Bottom)<=1&&oa.V=="bottom"){a.V="bottom";break;}
        }
      }
      if(a.HRef!=null&&DependsOn(self,a.HRef,anchors)){a.H="free";a.HRef=null;}
      if(a.VRef!=null&&DependsOn(self,a.VRef,anchors)){a.V="free";a.VRef=null;}
      return a;
    }
    public static void StripRef(Anchor a,string dragged,Native.Rect r,Native.Rect area,double scale){
      double m=DockMargin*scale;int w=r.Right-r.Left,h=r.Bottom-r.Top;
      if(a.HRef==dragged){
        a.HRef=null;a.X=RatioX(r,area,scale);
        if(Math.Abs(r.Left-(area.Left+m))<=1)a.H="left";else if(Math.Abs(r.Right-(area.Right-m))<=1)a.H="right";else if(Math.Abs(r.Left-(area.Left+(area.Right-area.Left-w)/2))<=1)a.H="center";else a.H="free";
      }
      if(a.VRef==dragged){
        a.VRef=null;a.Y=RatioY(r,area,scale);
        if(Math.Abs(r.Top-(area.Top+m))<=1)a.V="top";else if(Math.Abs(r.Bottom-(area.Bottom-m))<=1)a.V="bottom";else if(Math.Abs(r.Top-(area.Top+(area.Bottom-area.Top-h)/2))<=1)a.V="middle";else a.V="free";
      }
    }
  }

  public class PanelWindow:Window {
    public readonly string Kind;
    public readonly WebView2CompositionControl Web;
    public IntPtr Handle{get{return new WindowInteropHelper(this).Handle;}}
    public bool Shown{get{return Handle!=IntPtr.Zero&&Native.IsWindowVisible(Handle);}}
    public bool WantsVisible{get{return requestedShown;}}
    public bool Collapsed,Ready;
    readonly Host host;readonly Border border;readonly RowDefinition bodyRow;readonly double expandedHeight,settingsHeight;
    readonly TextBlock summary;readonly Button collapse;
    bool initialized,settingsOpen,requestedShown,visibilityKnown,visibilityAnimating;
    int visibilityVersion;
    public double Scale{get{try{return Native.GetDpiForWindow(Handle)/96.0;}catch{return 1;}}}
    double FullHeight{get{return Kind=="connection"&&settingsOpen?settingsHeight:expandedHeight;}}
    public PanelWindow(Host owner,string kind,string title,double width,double height,double settings=0){
      host=owner;Kind=kind;Title="Blitz Camera · "+title;Icon=AppIcon.Image;Width=width;Height=height;expandedHeight=height;settingsHeight=settings;
      WindowStyle=WindowStyle.None;ResizeMode=ResizeMode.NoResize;AllowsTransparency=true;Background=Brushes.Transparent;ShowInTaskbar=false;ShowActivated=false;Topmost=false;
      WindowStartupLocation=WindowStartupLocation.Manual;Left=-32000;Top=-32000;
      if(host.Smoke){Opacity=0;Topmost=false;}
      border=new Border{CornerRadius=new CornerRadius(11),BorderThickness=new Thickness(1),BorderBrush=new SolidColorBrush(Color.FromArgb(190,66,81,83)),ClipToBounds=true};
      var grid=new Grid();grid.RowDefinitions.Add(new RowDefinition{Height=new GridLength(32)});bodyRow=new RowDefinition{Height=new GridLength(1,GridUnitType.Star)};grid.RowDefinitions.Add(bodyRow);
      var titlebar=new Grid{Background=Brushes.Transparent};
      titlebar.ColumnDefinitions.Add(new ColumnDefinition{Width=new GridLength(1,GridUnitType.Star)});titlebar.ColumnDefinitions.Add(new ColumnDefinition{Width=GridLength.Auto});
      titlebar.Children.Add(new TextBlock{Text=title,Margin=new Thickness(12,8,32,0),Foreground=new SolidColorBrush(Color.FromRgb(173,193,188)),FontSize=11,IsHitTestVisible=false,TextTrimming=TextTrimming.CharacterEllipsis});
      summary=new TextBlock{Margin=new Thickness(0,8,34,0),Foreground=new SolidColorBrush(Color.FromArgb(216,196,232,140)),FontSize=11,IsHitTestVisible=false,HorizontalAlignment=HorizontalAlignment.Right,Visibility=Visibility.Collapsed,TextTrimming=TextTrimming.CharacterEllipsis};
      Grid.SetColumn(summary,1);titlebar.Children.Add(summary);
      collapse=new Button{Content="−",Width=28,Height=25,HorizontalAlignment=HorizontalAlignment.Right,Margin=new Thickness(0,3,3,0),Background=Brushes.Transparent,Foreground=Brushes.White,BorderThickness=new Thickness(0),ToolTip="折叠"};
      Grid.SetColumnSpan(collapse,2);collapse.Click+=delegate{ToggleCollapsed();host.SaveCollapsed();host.WriteStatus();};titlebar.Children.Add(collapse);
      titlebar.MouseLeftButtonDown+=delegate(object s,MouseButtonEventArgs e){
        if(e.OriginalSource is Button)return;
        if(e.ClickCount==2){ToggleCollapsed();host.SaveCollapsed();host.WriteStatus();return;}
        try{
          host.DetachDependants(Kind);host.Dragging=true;
          try{DragMove();}finally{host.Dragging=false;}
          host.DockFromRect(this);
        }catch(InvalidOperationException){host.Dragging=false;}
      };
      SourceInitialized+=delegate{var s=HwndSource.FromHwnd(Handle);if(s!=null)s.AddHook(MovingHook);};
      // Keep a positive arranged surface even while its parent viewport is
      // clipped to a folded titlebar. A 0x0 composition capture is invalid.
      Web=new WebView2CompositionControl{MinWidth=64,MinHeight=64,Height=expandedHeight-34,VerticalAlignment=VerticalAlignment.Top};
      var viewport=new Grid{ClipToBounds=true};viewport.Children.Add(Web);Grid.SetRow(viewport,1);grid.Children.Add(titlebar);grid.Children.Add(viewport);border.Child=grid;Content=border;UpdateOpacity();
      Loaded+=async delegate{
        if(initialized)return;initialized=true;
        try{
          await Web.EnsureCoreWebView2Async(host.Environment);Web.DefaultBackgroundColor=System.Drawing.Color.Transparent;host.ConfigureWeb(Web.CoreWebView2);
          Web.CoreWebView2.WebMessageReceived+=delegate(object s,CoreWebView2WebMessageReceivedEventArgs e){host.Message(this,e);};
          Web.CoreWebView2.NavigationCompleted+=delegate(object s,CoreWebView2NavigationCompletedEventArgs e){Ready=e.IsSuccess;SendStatus();host.WriteStatus();};
          Web.CoreWebView2.Navigate(host.Url+"overlay?panel="+Kind);
        }catch(Exception e){File.WriteAllText(Path.Combine(host.Root,"output/overlay-error.txt"),e.ToString());}
      };
    }
    public bool SetShown(bool value,bool animate=false){
      // Window.Hide propagates a zero capture size to WebView2's composition
      // control on some drivers. Hide the HWND without collapsing its layout.
      // A focus transition can hide one HWND independently of our requested
      // state. Only skip a request when the real window still agrees with it.
      bool interactive=IsHitTestVisible==value&&(Handle==IntPtr.Zero||((Native.GetWindowLong(Handle,-20)&0x20)==0)==value);
      bool settled=!visibilityAnimating&&!border.HasAnimatedProperties&&Shown==value&&border.Opacity==(value?1:0);
      if(visibilityKnown&&requestedShown==value&&interactive&&(settled||(animate&&visibilityAnimating&&Shown))){
        if(value)RestoreTopmost();
        SendStatus();
        return false;
      }
      visibilityKnown=true;requestedShown=value;int version=++visibilityVersion;
      double from=Shown?border.Opacity:0,target=value?1:0;
      visibilityAnimating=false;
      border.BeginAnimation(UIElement.OpacityProperty,null);border.Opacity=from;
      IsHitTestVisible=value;
      bool created=value&&!IsVisible;
      if(created)Show();
      if(Handle!=IntPtr.Zero){
        // A fading window must not intercept clicks intended for the newly focused app.
        int style=Native.GetWindowLong(Handle,-20);
        Native.SetWindowLong(Handle,-20,value?style&~0x20:style|0x20);
        if(value){if(!Shown)Native.ShowWindow(Handle,4);RestoreTopmost();}
      }
      if(animate&&Shown&&Math.Abs(from-target)>.001){
        visibilityAnimating=true;
        var fade=new DoubleAnimation(from,target,TimeSpan.FromMilliseconds(140)){EasingFunction=new QuadraticEase{EasingMode=EasingMode.EaseInOut}};
        fade.Completed+=delegate{CompleteVisibility(value,version);};
        border.BeginAnimation(UIElement.OpacityProperty,fade,HandoffBehavior.SnapshotAndReplace);
      }else CompleteVisibility(value,version);
      SendStatus();
      return created;
    }
    void CompleteVisibility(bool value,int version){
      if(version!=visibilityVersion||value!=requestedShown)return;
      visibilityAnimating=false;
      border.BeginAnimation(UIElement.OpacityProperty,null);border.Opacity=value?1:0;
      if(!value){Topmost=false;if(Handle!=IntPtr.Zero&&Shown)Native.ShowWindow(Handle,0);}
    }
    void RestoreTopmost(){
      bool topmost=host.Game!=IntPtr.Zero&&!host.Smoke;
      Topmost=topmost;
      if(Handle!=IntPtr.Zero&&((Native.GetWindowLong(Handle,-20)&0x8)!=0)!=topmost)
        Native.SetWindowPos(Handle,new IntPtr(topmost?-1:-2),0,0,0,0,0x13);
    }
    public void ToggleCollapsed(){if(Collapsed)Expand();else{Collapsed=true;bodyRow.Height=new GridLength(0);Height=34;summary.Visibility=Visibility.Visible;collapse.Content="+";collapse.ToolTip="展开";host.PositionAll();}}
    public void Expand(){Collapsed=false;Web.Height=FullHeight-34;Height=FullHeight;bodyRow.Height=new GridLength(1,GridUnitType.Star);summary.Visibility=Visibility.Collapsed;collapse.Content="−";collapse.ToolTip="折叠";host.PositionAll();}
    public void SetSettingsOpen(bool value){settingsOpen=value;if(!Collapsed){Web.Height=FullHeight-34;Height=FullHeight;host.PositionAll();}}
    public void SetSummary(string text){summary.Text=text;}
    Dictionary<string,Native.Rect> OtherRects(){
      var d=new Dictionary<string,Native.Rect>();
      foreach(var p in host.Panels.Values)if(p!=this&&p.Handle!=IntPtr.Zero&&p.Shown){Native.Rect o;if(Native.GetWindowRect(p.Handle,out o))d[p.Kind]=o;}
      return d;
    }
    IntPtr MovingHook(IntPtr hwnd,int msg,IntPtr w,IntPtr l,ref bool handled){
      if(msg!=0x0216)return IntPtr.Zero;
      var r=(Native.Rect)Marshal.PtrToStructure(l,typeof(Native.Rect));
      Marshal.StructureToPtr(PanelLayout.SnapMoving(r,host.Area,Math.Max(.5,Scale),OtherRects()),l,true);
      handled=true;return new IntPtr(1);
    }
    public void UpdateOpacity(){border.Background=new SolidColorBrush(Color.FromArgb((byte)(255*host.Opacity/100),15,22,28));}
    public void Send(object value){try{if(Web.CoreWebView2!=null)Web.CoreWebView2.PostWebMessageAsJson(Host.Json.Serialize(value));}catch{}}
    public void SendStatus(){Send(host.Status());}
  }

  public class Entry {
    [STAThread]public static void Main(string[] args){
      string root=args.Length>1?Path.GetFullPath(args[1]):Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"../.."));string url=args.Length>0?args[0]:"http://127.0.0.1:56593/";
      Uri p;if(!Uri.TryCreate(url,UriKind.Absolute,out p)||p.Scheme!="http"||p.Host!="127.0.0.1"||p.AbsolutePath!="/"||!string.IsNullOrEmpty(p.UserInfo))return;
      Directory.CreateDirectory(Path.Combine(root,"output"));bool created;var mutex=new Mutex(true,"Local\\BlitzCameraOverlay-"+p.Port,out created);var signal=new EventWaitHandle(false,EventResetMode.AutoReset,"Local\\BlitzCameraOverlayShow-"+p.Port);
      try{Native.SetProcessDpiAwarenessContext(new IntPtr(-4));}catch{}
      bool workbench=args.Length>2&&args[2]=="workbench";
      var workSignal=new EventWaitHandle(false,EventResetMode.AutoReset,"Local\\BlitzCameraWorkbenchShow-"+p.Port);
      if(!created){if(workbench)workSignal.Set();else signal.Set();workSignal.Dispose();signal.Dispose();mutex.Dispose();return;}
      var app=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};var host=new Host(url,root,workbench);
      var registered=ThreadPool.RegisterWaitForSingleObject(signal,delegate{app.Dispatcher.BeginInvoke(new Action(host.Reveal));},null,Timeout.Infinite,false);
      var registeredWorkbench=ThreadPool.RegisterWaitForSingleObject(workSignal,delegate{app.Dispatcher.BeginInvoke(new Action(delegate {host.OpenWorkbench();}));},null,Timeout.Infinite,false);
      app.Startup+=delegate{host.Start();};app.DispatcherUnhandledException+=delegate(object s,DispatcherUnhandledExceptionEventArgs e){File.WriteAllText(Path.Combine(root,"output/overlay-error.txt"),e.Exception.ToString());e.Handled=true;host.Shutdown();};
      app.Run();registered.Unregister(null);registeredWorkbench.Unregister(null);workSignal.Dispose();signal.Dispose();mutex.ReleaseMutex();mutex.Dispose();
    }
  }
}
