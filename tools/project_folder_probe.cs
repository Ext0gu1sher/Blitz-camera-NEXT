// Real workbench/Shell activation acceptance using a disposable project folder.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Reflection;
using System.Collections.Generic;
using System.Text;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Interop;
using BlitzCamera;
using Microsoft.Web.WebView2.Core;

public static class ProjectFolderProbe {
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h,StringBuilder text,int max);
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h,StringBuilder text,int max);
  [DllImport("user32.dll")] static extern bool PostMessage(IntPtr h,uint msg,IntPtr w,IntPtr l);
  static string Text(IntPtr h,bool kind=false){var s=new StringBuilder(512);if(kind)GetClassName(h,s,s.Capacity);else GetWindowText(h,s,s.Capacity);return s.ToString();}
  static async Task Wait(Func<Task<bool>> check){for(int i=0;i<160;i++){if(await check())return;await Task.Delay(100);}throw new Exception("Timed out waiting for native folder activation");}
  static void LookupOnly(string root){
    object shell=null,windows=null;
    try{
      var lookup=typeof(WorkbenchWindow).GetMethod("FindProjectFolderWindow",BindingFlags.NonPublic|BindingFlags.Static);
      shell=Activator.CreateInstance(Type.GetTypeFromProgID("Shell.Application",true));
      windows=shell.GetType().InvokeMember("Windows",BindingFlags.InvokeMethod,null,shell,null);
      int count=Convert.ToInt32(windows.GetType().InvokeMember("Count",BindingFlags.GetProperty,null,windows,null)),matched=0;
      var folders=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
      for(int i=0;i<count;i++){
        object item=null;
        try{
          item=windows.GetType().InvokeMember("Item",BindingFlags.InvokeMethod,null,windows,new object[]{i});
          if(item==null)continue;
          Uri location;
          if(!Uri.TryCreate(Convert.ToString(item.GetType().InvokeMember("LocationURL",BindingFlags.GetProperty,null,item,null)),UriKind.Absolute,out location)||!location.IsFile)continue;
          var hwnd=new IntPtr(Convert.ToInt64(item.GetType().InvokeMember("HWND",BindingFlags.GetProperty,null,item,null)));
          if(Text(hwnd,true)!="CabinetWClass"&&Text(hwnd,true)!="ExploreWClass")continue;
          folders.Add(location.LocalPath);
        }finally{if(item!=null&&Marshal.IsComObject(item))Marshal.ReleaseComObject(item);}
      }
      foreach(string directory in folders){
        IntPtr found=(IntPtr)lookup.Invoke(null,new object[]{directory});
        if(found==IntPtr.Zero)throw new Exception("Existing Explorer folder was not found");
        IntPtr alternate=(IntPtr)lookup.Invoke(null,new object[]{directory.ToUpperInvariant().TrimEnd('\\','/')+"/"});
        if(found!=alternate)throw new Exception("Folder lookup differs for case or trailing separator");
        matched++;
      }
      if((IntPtr)lookup.Invoke(null,new object[]{Path.Combine(root,"No-Explorer-"+Guid.NewGuid())})!=IntPtr.Zero)throw new Exception("Unrelated Explorer matched");
      File.WriteAllText(Path.Combine(root,"result.json"),Host.Json.Serialize(new{passed=true,lookupOnly=true,existingFoldersMatched=matched,noUnrelatedMatch=true,noWindowsOpenedOrActivated=true,foregroundActivationTested=false}));
    }catch(Exception error){File.WriteAllText(Path.Combine(root,"error.txt"),error.ToString());Environment.ExitCode=1;}
    finally{
      if(windows!=null&&Marshal.IsComObject(windows))Marshal.ReleaseComObject(windows);
      if(shell!=null&&Marshal.IsComObject(shell))Marshal.ReleaseComObject(shell);
    }
  }
  [STAThread] public static void Main(string[] args){
    if(args[0]=="--lookup-only"){LookupOnly(args[1]);return;}
    var app=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};
    app.Startup+=async delegate{
      WorkbenchWindow window=null;IntPtr explorer=IntPtr.Zero;string folder=args[2],name=Path.GetFileName(folder),stage="startup";
      int cycles=args.Length>3?int.Parse(args[3]):1;
      try{
        var host=new Host(args[0],args[1],true);
        host.Environment=await CoreWebView2Environment.CreateAsync(null,Path.Combine(args[1],"webview"));
        window=new WorkbenchWindow(host);host.Workbench=window;window.Title="Blitz Camera · Folder acceptance";
        window.Show();
        await Wait(async()=>window.Ready&&await window.Web.ExecuteScriptAsync("document.body.dataset.appReady==='true'&&!homeLoading&&!!nativeHostState?.projectFolder")=="true");
        IntPtr handle=new WindowInteropHelper(window).Handle;
        for(int pass=0;pass<cycles;pass++){
          stage="workbench foreground "+pass;
          // Ask only this probe's Explorer window to minimize itself, so the
          // shell performs its normal focus transfer without global input.
          if(pass>0){await Task.Delay(500);PostMessage(explorer,0x112,new IntPtr(0xF020),IntPtr.Zero);await Task.Delay(500);}
          window.Activate();window.Web.Focus();
          await Wait(()=>Task.FromResult(Native.GetAncestor(Native.GetForegroundWindow(),3)==handle));
          if(pass==1)Native.ShowWindow(explorer,4); // Reuse a visible, inactive folder.
          stage="explorer foreground "+pass;
          await window.Web.ExecuteScriptAsync("document.querySelector('.home-more').click();document.querySelector('[data-home-action=folder]').dispatchEvent(new MouseEvent('click',{bubbles:true,detail:1}));");
          await Wait(()=>{
            IntPtr h=Native.GetForegroundWindow();
            bool ok=Text(h,true)=="CabinetWClass"&&Text(h).Contains(name);
            if(ok)explorer=h;return Task.FromResult(ok);
          });
          await Wait(async()=>await window.Web.ExecuteScriptAsync("!state.busy&&folderOpenRequests.size===0")=="true");
          if(await window.Web.ExecuteScriptAsync("!!document.activeElement.closest('.home-project')")!="false")throw new Exception("Mouse action left a project focused");
          if((Native.GetWindowLong(explorer,-20)&8)!=0)throw new Exception("Explorer was made permanently topmost");
        }
        File.WriteAllText(Path.Combine(args[1],"result.json"),Host.Json.Serialize(new{passed=true,newFolderForeground=true,reusedFolderChecked=cycles>=2,minimizedFolderChecked=cycles>=3,noPermanentTopmost=true,mouseFocusCleared=true,cycles=cycles,gameAccess=false}));
      }catch(Exception error){
        IntPtr h=Native.GetForegroundWindow();
        File.WriteAllText(Path.Combine(args[1],"error.txt"),stage+"\n"+Text(h,true)+" "+Text(h)+"\n"+error);Environment.ExitCode=1;
      }
      finally{
        if(explorer!=IntPtr.Zero&&Text(explorer).Contains(name))PostMessage(explorer,0x10,IntPtr.Zero,IntPtr.Zero);
        if(window!=null){window.AllowClose=true;window.Web.Dispose();window.Close();}
        app.Shutdown();
      }
    };
    app.Run();
  }
}
