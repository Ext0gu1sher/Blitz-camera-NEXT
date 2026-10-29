// Real HWND ordering, with invisible offscreen fixtures and no browser/game startup.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Threading;
using BlitzCamera;

public static class OverlayVisibilityProbe {
  delegate bool EnumWindowProc(IntPtr hwnd,IntPtr param);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowProc callback,IntPtr param);
  [StructLayout(LayoutKind.Sequential)] struct WindowPos { public IntPtr hwnd,after;public int x,y,cx,cy;public uint flags; }
  static int activations,zOrderChanges;
  static void Require(bool condition,string message){if(!condition)throw new Exception(message);}
  static bool Above(IntPtr window,IntPtr reference){
    var windows=new List<IntPtr>();EnumWindows(delegate(IntPtr h,IntPtr p){windows.Add(h);return true;},IntPtr.Zero);
    int a=windows.IndexOf(window),b=windows.IndexOf(reference);Require(a>=0&&b>=0,"Fixture missing from desktop order");return a<b;
  }
  static void Raise(IntPtr hwnd){Require(Native.SetWindowPos(hwnd,new IntPtr(-1),0,0,0,0,0x13),"Could not arrange fixture");}
  static bool Topmost(IntPtr hwnd){return (Native.GetWindowLong(hwnd,-20)&8)!=0;}
  static void Pump(){
    var frame=new DispatcherFrame();Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.ApplicationIdle,new Action(delegate{frame.Continue=false;}));Dispatcher.PushFrame(frame);
  }
  static Window Fixture(){
    var window=new Window{Width=1280,Height=900,Left=-32000,Top=-32000,WindowStartupLocation=WindowStartupLocation.Manual,
      WindowStyle=WindowStyle.None,AllowsTransparency=true,Background=Brushes.Transparent,Opacity=0,ShowActivated=false,ShowInTaskbar=false};
    window.Activated+=delegate{activations++;};window.Show();return window;
  }
  [STAThread] public static void Main(string[] args){
    try{Run(args);}catch(Exception error){Console.Error.WriteLine(error);Environment.ExitCode=1;}
  }
  static void Run(string[] args){
    System.Environment.SetEnvironmentVariable("BLITZCAM_DESKTOP_SMOKE",null);
    var application=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};
    Directory.CreateDirectory(Path.Combine(args[0],"output"));
    var host=new Host("http://127.0.0.1:1/",args[0],false){GameFeatures=true};
    var game=Fixture();var other=Fixture();host.Game=new WindowInteropHelper(game).Handle;
    try{
      foreach(string kind in new[]{"connection","telemetry","capture","keyframes"}){
        var panel=new PanelWindow(host,kind,kind,kind=="connection"?Host.ConnectionW:272,kind=="connection"?Host.ConnectionH:200){Opacity=0};
        // Exercise production visibility and topmost code without creating WebView processes.
        typeof(PanelWindow).GetField("initialized",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(panel,true);
        panel.Activated+=delegate{activations++;};host.Panels.Add(kind,panel);
      }
      host.RefreshVisibility(true,host.Game);Pump();
      foreach(var panel in host.Panels.Values)HwndSource.FromHwnd(panel.Handle).AddHook(delegate(IntPtr hwnd,int msg,IntPtr w,IntPtr l,ref bool handled){
        if(msg==0x46&&(((WindowPos)Marshal.PtrToStructure(l,typeof(WindowPos))).flags&4)==0)zOrderChanges++;
        return IntPtr.Zero;
      });
      var cycles=new List<object>();bool recovered=true,stable=true,layoutPreserved=true;
      for(int cycle=0;cycle<20;cycle++){
        host.Hidden=true;host.RefreshVisibility(true,host.Game);host.Hidden=false;host.RefreshVisibility(true,host.Game);Pump();
        // The game can overtake only the connection panel, even though its
        // WS_VISIBLE and WS_EX_TOPMOST flags still say it is shown and topmost.
        Raise(host.Game);
        foreach(var panel in host.Panels.Values.Where(p=>p.Kind!="connection"))Raise(panel.Handle);
        var top=host.Panels["connection"];
        Require(top.Shown&&Topmost(top.Handle)&&!Above(top.Handle,host.Game),"Did not reproduce hidden connection window");
        Require(host.Panels.Values.Where(p=>p!=top).All(p=>Above(p.Handle,host.Game)),"Other panels should remain above game");
        Native.Rect before,after;Native.GetWindowRect(top.Handle,out before);
        host.RefreshVisibility(false,host.Game);Pump();
        bool restored=Above(top.Handle,host.Game);recovered&=restored;
        Native.GetWindowRect(top.Handle,out after);layoutPreserved&=before.Left==after.Left&&before.Top==after.Top&&before.Right==after.Right&&before.Bottom==after.Bottom;
        int mutations=zOrderChanges;for(int tick=0;tick<20;tick++)host.RefreshVisibility(false,host.Game);
        bool unchanged=zOrderChanges==mutations;stable&=unchanged;
        cycles.Add(new{cycle=cycle+1,recoveredWithoutClick=restored,stableOrder=unchanged});
      }
      // Also cover non-topmost games and real style drift.
      Native.SetWindowPos(host.Game,new IntPtr(-2),0,0,0,0,0x13);
      var connection=host.Panels["connection"];
      Native.SetWindowPos(connection.Handle,new IntPtr(-2),0,0,0,0,0x13);
      host.RefreshVisibility(true,host.Game);
      bool styleRestored=Topmost(connection.Handle)&&Above(connection.Handle,host.Game);
      host.RefreshVisibility(true,new WindowInteropHelper(other).Handle);
      bool backgroundHidden=host.Panels.Values.All(p=>!p.Shown&&!Topmost(p.Handle));
      host.RefreshVisibility(true,host.Game);
      bool foregroundRestored=host.Panels.Values.All(p=>p.Shown&&Above(p.Handle,host.Game));
      host.Hidden=true;host.RefreshVisibility(true,host.Game);
      bool manualHidePreserved=host.Panels.Values.All(p=>!p.Shown&&!Topmost(p.Handle));
      host.Hidden=false;host.Game=IntPtr.Zero;host.RefreshVisibility(true,IntPtr.Zero);
      bool noGameNotTopmost=host.Panels.Values.All(p=>!Topmost(p.Handle));
      var result=new{recoveredWithoutClick=recovered,stableOrder=stable,layoutPreserved,styleRestored,backgroundHidden,foregroundRestored,manualHidePreserved,noGameNotTopmost,noActivation=activations==0,cycles};
      Console.WriteLine(Host.Json.Serialize(result));
      Require(stable&&layoutPreserved&&styleRestored&&backgroundHidden&&foregroundRestored&&manualHidePreserved&&noGameNotTopmost&&activations==0,"Visibility regression");
      if(args.Length<2||args[1]!="--baseline")Require(recovered,"Connection panel remains beneath game despite visible/topmost flags");
    }finally{
      foreach(var panel in host.Panels.Values){panel.Web.Dispose();panel.Close();}game.Close();other.Close();application.Shutdown();
    }
  }
}
