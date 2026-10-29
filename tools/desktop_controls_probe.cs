// Isolated Windows hotkey probe: no WebView, tray, game discovery or focus.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Threading;
using System.Windows.Interop;
using System.Windows.Threading;
using BlitzCamera;

public static class DesktopControlsProbe {
  [STAThread] public static void Main(string[] args){
    try{Run(args);}catch(Exception error){Console.Error.WriteLine(error);Environment.ExitCode=1;}
  }
  static void Run(string[] args){
    Directory.CreateDirectory(Path.Combine(args[1],"output"));
    var host=new Host(args[0],args[1],false){GameFeatures=true};
    Native.WinEventProc foregroundCallback=delegate {};
    var foregroundHook=Native.SetWinEventHook(3,3,IntPtr.Zero,foregroundCallback,0,0,0);
    if(foregroundHook==IntPtr.Zero||!Native.UnhookWinEvent(foregroundHook))throw new Exception("Foreground event hook could not be installed and removed");
    GC.KeepAlive(foregroundCallback);
    var flags=BindingFlags.Instance|BindingFlags.NonPublic;
    using(var blocker=new HwndSource(new HwndSourceParameters("Blitz Camera test blocker"){ParentWindow=new IntPtr(-3),WindowStyle=0}))
    using(var window=new HwndSource(new HwndSourceParameters("Blitz Camera test hotkeys"){ParentWindow=new IntPtr(-3),WindowStyle=0})){
      var keys=new List<string>();
      for(int n=7;n<=11;n++)if(Native.RegisterHotKey(blocker.Handle,100+n,0x4003,(uint)(111+n)))keys.Add("F"+n);
      try{
        if(keys.Count<3)throw new Exception("Need three available Ctrl+Alt function keys for isolated conflict test");
        string hide=keys[0],capture=keys[1],blocked=keys[2];
        Native.UnregisterHotKey(blocker.Handle,100+int.Parse(hide.Substring(1)));
        Native.UnregisterHotKey(blocker.Handle,100+int.Parse(capture.Substring(1)));
        typeof(Host).GetField("hotkeyWindow",flags).SetValue(host,window);
        window.AddHook((HwndSourceHook)Delegate.CreateDelegate(typeof(HwndSourceHook),host,typeof(Host).GetMethod("Hotkey",flags)));
        host.ApplySettings(new Dictionary<string,object>{{"hideKey",hide},{"captureKey",capture}});
        if(!host.HideHotkeyRegistered||!host.CaptureHotkeyRegistered)throw new Exception("Global hotkeys did not register");
        bool rejected=false;
        try{host.ApplySettings(new Dictionary<string,object>{{"captureKey",hide}});}catch(ArgumentException){rejected=true;}
        if(!rejected||host.HideKey!=Host.ValidKey(hide)||host.CaptureKey!=Host.ValidKey(capture))throw new Exception("Duplicate assignment changed active keys");
        host.ApplySettings(new Dictionary<string,object>{{"captureKey",blocked}});
        if(host.HideKey!=Host.ValidKey(hide)||host.CaptureKey!=Host.ValidKey(capture)||!host.HideHotkeyRegistered||!host.CaptureHotkeyRegistered)throw new Exception("Occupied key did not roll back both registrations");
        if(((string[])host.Status()["warnings"]).Length==0)throw new Exception("Registration conflict was not visible");
        var custom=new List<string>();
        for(int vk=65;vk<=90&&custom.Count<2;vk++)if(Native.RegisterHotKey(blocker.Handle,200+vk,0x4007,(uint)vk)){Native.UnregisterHotKey(blocker.Handle,200+vk);custom.Add("Ctrl+Alt+Shift+Key"+(char)vk);}
        if(custom.Count<2)throw new Exception("Need two available custom key chords");
        host.ApplySettings(new Dictionary<string,object>{{"hideKey",custom[0]},{"captureKey",custom[1]}});
        if(host.HideKey!=custom[0]||host.CaptureKey!=custom[1]||!host.HideHotkeyRegistered||!host.CaptureHotkeyRegistered)throw new Exception("Custom chords did not register");
        var restored=new Host(args[0],args[1],false);
        if(restored.HideKey!=custom[0]||restored.CaptureKey!=custom[1])throw new Exception("Custom chords did not persist");
        host.SetShortcutCapture(true);
        uint customCode=Host.KeyCode(custom[0].Substring(custom[0].LastIndexOf('+')+1));
        if(!Native.RegisterHotKey(blocker.Handle,300,0x4007,customCode))throw new Exception("Shortcut capture did not release the global key");
        Native.UnregisterHotKey(blocker.Handle,300);host.SetShortcutCapture(false);
        if(!host.HideHotkeyRegistered||!host.CaptureHotkeyRegistered)throw new Exception("Shortcut capture did not restore global keys");
        foreach(string reserved in new[]{"Ctrl+KeyS","Ctrl+Shift+KeyZ","Alt+F4","Ctrl+Alt+F12","KeyH","Ctrl+Ctrl+KeyH"}){
          bool invalid=false;try{Host.ValidKey(reserved);}catch(ArgumentException){invalid=true;}if(!invalid)throw new Exception("Reserved chord accepted: "+reserved);
        }
        if(Host.KeyCode("KeyH")!=72||Host.KeyCode("Numpad4")!=100||Host.KeyCode("ArrowLeft")!=37||Host.KeyCode("Tab")!=9)throw new Exception("Physical keys did not map to Windows keys");
        // Dispatch the registered action while there are zero overlay windows.
        host.SetOverlayHidden(true);
        Native.SendMessage(window.Handle,0x312,new IntPtr(2),IntPtr.Zero);
        var pending=typeof(Host).GetField("capturePending",flags);
        for(int i=0;i<200&&(bool)pending.GetValue(host);i++){
          var frame=new DispatcherFrame();
          Dispatcher.CurrentDispatcher.BeginInvoke(DispatcherPriority.Background,new Action(delegate{frame.Continue=false;}));
          Dispatcher.PushFrame(frame);Thread.Sleep(25);
        }
        if((bool)pending.GetValue(host))throw new Exception("Global capture did not finish");
        if(!host.Hidden)throw new Exception("Global capture revealed the overlay");
        Console.WriteLine(Host.Json.Serialize(new{registered=true,duplicateRejected=true,occupiedRolledBack=true,conflictVisible=true,customChordsRegistered=true,customChordsPersist=true,recordingSuspendsGlobalKeys=true,reservedRejected=true,physicalKeyMapping=true,captureWithNoWindows=true,manualHidePreserved=true,foregroundHookAvailable=true}));
      }finally{
        Native.UnregisterHotKey(window.Handle,1);Native.UnregisterHotKey(window.Handle,2);
        for(int n=7;n<=12;n++)Native.UnregisterHotKey(blocker.Handle,100+n);
      }
    }
  }
}
