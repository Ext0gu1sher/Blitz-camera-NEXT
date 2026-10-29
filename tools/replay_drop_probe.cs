// Exercise the OLE drop target registered on the real WPF HWND, without global input or game access.
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Interop;
using Microsoft.Web.WebView2.Core;
using BlitzCamera;

public static class ReplayDropProbe {
  // Invoke the registered COM interface, not a fabricated WPF/DOM event. WPF's
  // managed OleDropTarget cannot be cast to a second managed interface with its GUID.
  sealed class NativeDropTarget:IDisposable {
    IntPtr pointer;
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FileCall(IntPtr self,[MarshalAs(UnmanagedType.Interface)]System.Runtime.InteropServices.ComTypes.IDataObject data,uint keys,Native.Point point,ref uint effect);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int OverCall(IntPtr self,uint keys,Native.Point point,ref uint effect);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int LeaveCall(IntPtr self);
    readonly FileCall enter,drop;readonly OverCall over;readonly LeaveCall leave;
    public NativeDropTarget(IntPtr registered){
      var iid=new Guid("00000122-0000-0000-C000-000000000046");
      Marshal.ThrowExceptionForHR(Marshal.QueryInterface(registered,ref iid,out pointer));
      var table=Marshal.ReadIntPtr(pointer);
      enter=(FileCall)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(table,3*IntPtr.Size),typeof(FileCall));
      over=(OverCall)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(table,4*IntPtr.Size),typeof(OverCall));
      leave=(LeaveCall)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(table,5*IntPtr.Size),typeof(LeaveCall));
      drop=(FileCall)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(table,6*IntPtr.Size),typeof(FileCall));
    }
    public int DragEnter(System.Runtime.InteropServices.ComTypes.IDataObject data,uint keys,Native.Point point,ref uint effect){return enter(pointer,data,keys,point,ref effect);}
    public int DragOver(uint keys,Native.Point point,ref uint effect){return over(pointer,keys,point,ref effect);}
    public int DragLeave(){return leave(pointer);}
    public int Drop(System.Runtime.InteropServices.ComTypes.IDataObject data,uint keys,Native.Point point,ref uint effect){return drop(pointer,data,keys,point,ref effect);}
    public void Dispose(){if(pointer!=IntPtr.Zero){Marshal.Release(pointer);pointer=IntPtr.Zero;}}
  }
  [DllImport("user32.dll",CharSet=CharSet.Unicode)] static extern IntPtr GetProp(IntPtr hwnd,string name);
  static WorkbenchWindow targetWindow;
  static NativeDropTarget dropTarget;
  [STAThread] public static void Main(string[] args){
    Console.OutputEncoding=System.Text.Encoding.UTF8;
    var app=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};
    app.Startup+=async delegate{
      try{await Run(args);Console.WriteLine("PASS: window-registered Windows OLE drops across home blank area, sidebar and workbench panels; enter/leave, creation, Unicode path, persistence, key preservation, invalid/multiple files, busy guard, picker and cancel.");}
      catch(Exception error){Console.Error.WriteLine(error);Environment.ExitCode=1;}
      finally{app.Shutdown();}
    };
    app.Run();
  }
  static async Task Run(string[] args){
    var host=new Host(args[0],args[1],true);
    host.Environment=await CoreWebView2Environment.CreateAsync(null,Path.Combine(args[1],"webview"));
    var window=new WorkbenchWindow(host){Left=-32000,Top=-32000,Width=1440,Height=1000,
      WindowStartupLocation=WindowStartupLocation.Manual,Opacity=0,ShowInTaskbar=false,ShowActivated=false};
    // Do not call Host.Start: the fixture registers no global hotkeys, tray or game watchers.
    window.Show();
    try{
      for(int i=0;i<150&&!window.Ready;i++)await Task.Delay(100);
      var web=window.Web.CoreWebView2;if(web==null)throw new Exception("WebView did not initialize");
      targetWindow=window;
      var pointer=GetProp(new WindowInteropHelper(window).Handle,"OleDropTargetInterface");
      if(pointer==IntPtr.Zero)throw new Exception("No Windows OLE drop target registered on workbench HWND");
      dropTarget=new NativeDropTarget(pointer);
      await Wait(web,"state.loaded && state.home && !state.project && document.body.dataset.appReady==='true'","empty home");
      await web.ExecuteScriptAsync("window.testErrors=[];addEventListener('error',e=>testErrors.push(e.message));");
      await Shot(web,args[1],"home.png");
      foreach(var point in new[]{new Point(80,200),new Point(700,300),new Point(1200,750)}){
        await Drop(web,new[]{args[2]},"dragEnter",point);
        await Wait(web,"!$('replayDropOverlay').hidden","home full-window native drag cue");
        Marshal.ThrowExceptionForHR(dropTarget.DragLeave());
        await Wait(web,"$('replayDropOverlay').hidden","native leave clears cue");
      }
      await Drop(web,new[]{args[2]},"dragEnter");
      await Wait(web,"!$('replayDropOverlay').hidden && $('replayDropOverlay').textContent.includes('新建项目')","home drag cue");
      await Shot(web,args[1],"drag.png");
      await Drop(web,new[]{args[2]},"dragOver");await Drop(web,new[]{args[2]},"drop");
      string first=Host.Json.Serialize(args[2]),second=Host.Json.Serialize(args[3]);
      await Wait(web,"state.timeline?.replay_file==="+first+" && !state.home && !state.busy && !state.dirty","create and save dropped replay");
      await Wait(web,"replayPreviewPane?.status==='error' && $('previewFile').textContent.includes('第一场')","preview follows binding even on parse failure");
      await web.ExecuteScriptAsync("window.initialProject=state.projectPath;window.initialTracks=JSON.stringify(state.tracks);window.initialSpeed=JSON.stringify(sequenceEditor.doc.speed);");
      await Shot(web,args[1],"workbench.png");
      foreach(var point in new[]{new Point(80,200),new Point(850,250),new Point(800,780)}){
        await Drop(web,new[]{args[2]},"dragEnter",point);
        await Wait(web,"!$('replayDropOverlay').hidden && $('replayDropOverlay').textContent.includes('当前项目')","workbench all panels native drag cue");
        Marshal.ThrowExceptionForHR(dropTarget.DragLeave());
        await Wait(web,"$('replayDropOverlay').hidden","workbench native leave clears cue");
      }
      await Drop(web,new[]{args[4]},"drop");
      await Wait(web,"$('toast').textContent.includes('仅支持') && state.projectPath===initialProject","wrong extension rejected");
      await Drop(web,new[]{args[2],args[3]},"drop");
      await Wait(web,"$('toast').textContent.includes('每次拖入一个')","multiple files rejected");
      await web.ExecuteScriptAsync("state.busy=true;updateButtons();");
      await Drop(web,new[]{args[3]},"drop",new Point(800,780));
      await Wait(web,"state.timeline.replay_file==="+first+" && ($('toast').textContent.includes('等待') || $('replayDropOverlay').classList.contains('blocked'))","busy drop rejected");
      await web.ExecuteScriptAsync("state.busy=false;updateButtons();clearReplayDrop();");
      await Drop(web,new[]{args[5]},"drop");
      await Wait(web,"!state.busy && state.timeline.replay_file==="+first+" && !$('toast').hidden && $('toast').classList.contains('error')","corrupt replay retains binding");
      await Drop(web,new[]{args[3]},"drop");
      await Wait(web,"state.timeline.replay_file==="+second+" && !state.busy","replace replay binding");
      await Wait(web,"state.projectPath===initialProject && JSON.stringify(state.tracks)===initialTracks && JSON.stringify(sequenceEditor.doc.speed)===initialSpeed","authored keys preserved");
      await web.ExecuteScriptAsync("window.BlitzFlushEditorSession();");
      await Wait(web,"!state.dirty && !state.busy","replacement persisted");
      await web.ExecuteScriptAsync("showHome(true);$('homeNewName').value='自定义拖放项目';");
      await Drop(web,new[]{args[2]},"drop",new Point(1200,750));
      await Wait(web,"!state.home && !state.busy && !state.dirty && state.projectPath.includes('自定义拖放项目')","custom project name");
      // The same entry supports the existing native chooser, including cancellation.
      await web.ExecuteScriptAsync("showHome(true);$('homeNewName').value='选择回放项目';$('homeReplayDrop').click();");
      await Wait(web,"!state.home && !state.busy && state.projectPath.includes('选择回放项目') && state.timeline.replay_file==="+first,"home chooser");
      await web.ExecuteScriptAsync("showHome(true);window.beforeCancel=state.projectPath;$('homeReplayDrop').click();");
      await Wait(web,"state.home && !state.busy && !homeOpening && !state.selectingReplay && state.projectPath===beforeCancel","cancel preserves project");
      await Wait(web,"testErrors.length===0","no renderer errors");
      await web.ExecuteScriptAsync("window.BlitzFlushEditorSession();");
      await Wait(web,"!state.dirty","final saved state");
    }finally{if(dropTarget!=null)dropTarget.Dispose();window.AllowClose=true;window.Web.Dispose();window.Close();}
  }
  static async Task Drop(CoreWebView2 web,string[] files,string type,Point? at=null){
    if(type=="drop"){await Drop(web,files,"dragEnter",at);await Drop(web,files,"dragOver",at);}
    var screen=targetWindow.PointToScreen(at??new Point(700,300));
    var point=new Native.Point{X=(int)screen.X,Y=(int)screen.Y};uint effect=1;
    var data=new System.Windows.Forms.DataObject(System.Windows.Forms.DataFormats.FileDrop,files);
    int result=type=="dragEnter"?dropTarget.DragEnter(data,1,point,ref effect):
      type=="dragOver"?dropTarget.DragOver(1,point,ref effect):dropTarget.Drop(data,0,point,ref effect);
    Marshal.ThrowExceptionForHR(result);
    if(effect!=1)throw new Exception("Windows rejected "+type+" at "+point.X+","+point.Y+" (effect "+effect+")");
    await Task.Delay(60);
  }
  static async Task Wait(CoreWebView2 web,string expression,string name){
    for(int i=0;i<150;i++){if(await web.ExecuteScriptAsync("Boolean("+expression+")")=="true")return;await Task.Delay(100);}
    throw new Exception("Failed: "+name+"; "+await web.ExecuteScriptAsync("JSON.stringify({home:state.home,busy:state.busy,loaded:state.loaded,dirty:state.dirty,path:state.projectPath,timeline:state.timeline,toast:$('toast').textContent,errors:window.testErrors})"));
  }
  static async Task Shot(CoreWebView2 web,string root,string name){
    using(var file=File.Create(Path.Combine(root,name)))await web.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png,file);
  }
}
