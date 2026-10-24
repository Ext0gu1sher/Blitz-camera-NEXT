// Test-only offscreen WebView2 probe: no game discovery or global desktop input.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using BlitzCamera;
using Forms=System.Windows.Forms;

public static class KeyframeClipboardProbe {
  static readonly List<string> Checks=new List<string>();
  static bool ownsClipboard;
  static uint ownedSequence;
  [DllImport("user32.dll")] static extern uint GetClipboardSequenceNumber();
  static Forms.DataObject backup;
  static bool initiallyEmpty;
  static bool restored;
  [STAThread] public static void Main(string[] args){
    Console.OutputEncoding=System.Text.Encoding.UTF8;
    var app=new Application{ShutdownMode=ShutdownMode.OnExplicitShutdown};
    app.Startup+=async delegate{
      try{
        SnapshotClipboard();
        await Run(args);
        RestoreClipboard();
        Console.WriteLine(Host.Json.Serialize(new{passed=true,checks=Checks.ToArray(),clipboardRestored=restored,inputDelivery="renderer-targeted CDP; no global input",windows="offscreen, opacity zero, never activated"}));
      }catch(Exception error){Console.Error.WriteLine(error);Environment.ExitCode=1;}
      finally{try{RestoreClipboard();}catch(Exception error){Console.Error.WriteLine("Clipboard restore failed: "+error);Environment.ExitCode=1;}app.Shutdown();}
    };
    app.Run();
  }
  static void SnapshotClipboard(){
    var data=Forms.Clipboard.GetDataObject();
    initiallyEmpty=data==null||data.GetFormats(false).Length==0;
    backup=new Forms.DataObject();
    if(data==null)return;
    foreach(string format in data.GetFormats(false)){
      object value=data.GetData(format,false);
      if(value==null)continue;
      var stream=value as MemoryStream;
      if(stream!=null)value=new MemoryStream(stream.ToArray());
      var bitmap=value as System.Drawing.Bitmap;
      if(bitmap!=null)value=bitmap.Clone();
      backup.SetData(format,false,value);
    }
  }
  static void RestoreClipboard(){
    if(!ownsClipboard||restored)return;
    // A concurrent user copy supersedes the test and must never be overwritten.
    if(GetClipboardSequenceNumber()!=ownedSequence){Checks.Add("concurrent clipboard update preserved");ownsClipboard=false;return;}
    if(initiallyEmpty)Forms.Clipboard.Clear();else Forms.Clipboard.SetDataObject(backup,true);
    restored=true;ownsClipboard=false;
  }
  static void TrackClipboard(uint previous){uint sequence=GetClipboardSequenceNumber();if(sequence!=previous){ownsClipboard=true;ownedSequence=sequence;}}
  static async Task Run(string[] args){
    var window=new Window{Title="Blitz Camera isolated clipboard acceptance",Left=-32000,Top=-32000,Width=1100,Height=600,
      WindowStartupLocation=WindowStartupLocation.Manual,Opacity=0,ShowInTaskbar=false,ShowActivated=false};
    var grid=new Grid();grid.RowDefinitions.Add(new RowDefinition());grid.RowDefinitions.Add(new RowDefinition());
    var first=new WebView2CompositionControl();var second=new WebView2CompositionControl();
    grid.Children.Add(first);grid.Children.Add(second);Grid.SetRow(second,1);window.Content=grid;window.Show();
    var host=new Host(args[0],args[1],false);
    var environment=await CoreWebView2Environment.CreateAsync(null,Path.Combine(args[1],"webview"));
    try{
      await first.EnsureCoreWebView2Async(environment);await second.EnsureCoreWebView2Async(environment);
      host.ConfigureWeb(first.CoreWebView2);host.ConfigureWeb(second.CoreWebView2);
      await Navigate(first.CoreWebView2,args[0]+"?first");await Navigate(second.CoreWebView2,args[0]+"?second");
      await Assert(first.CoreWebView2,"window.ready && !!window.BlitzKeyframeClipboard && !notices.length","first fixture ready");
      await Assert(second.CoreWebView2,"window.ready && !!window.BlitzKeyframeClipboard && !notices.length","second fixture ready");
      await first.CoreWebView2.CallDevToolsProtocolMethodAsync("Emulation.setFocusEmulationEnabled","{\"enabled\":true}");
      await second.CoreWebView2.CallDevToolsProtocolMethodAsync("Emulation.setFocusEmulationEnabled","{\"enabled\":true}");
      await first.CoreWebView2.ExecuteScriptAsync("editor.scroll.focus();true");
      uint clipboardSequence=GetClipboardSequenceNumber();
      await Click(first.CoreWebView2,"[data-action=copy]");
      TrackClipboard(clipboardSequence);
      string copied=Forms.Clipboard.ContainsText()?Forms.Clipboard.GetText():"";
      if(!copied.StartsWith("BlitzCamera keyframes\n"))throw new Exception("Toolbar execCommand did not reach native clipboard; "+await first.CoreWebView2.ExecuteScriptAsync("JSON.stringify({copies,notices,selected:[...editor.selected],clipboard:editor.clipboard,viewport:[innerWidth,innerHeight],button:document.querySelector('[data-action=copy]').outerHTML,rect:document.querySelector('[data-action=copy]').getBoundingClientRect().toJSON(),focused:document.hasFocus(),activation:navigator.userActivation.isActive})"));
      Checks.Add("toolbar execCommand copies tagged keyframes to Windows clipboard");
      await Assert(first.CoreWebView2,"copies.length===1 && copies[0].trusted && copies[0].types.includes('text/plain')","native trusted copy event");
      await second.CoreWebView2.ExecuteScriptAsync("editor.scroll.focus();true");
      await Key(second.CoreWebView2,"v",86);
      await Assert(second.CoreWebView2,"pastes.length===1 && pastes[0].trusted && editor.doc.tracks.x.some(k=>k.time_sec===10 && k.value===17) && editor.doc.tracks.y.some(k=>k.time_sec===14 && k.value===27) && changes.length===1 && !notices.length","cross-window native Ctrl+V at playhead");
      await Assert(second.CoreWebView2,"pastes[0].types.includes('application/x-blitzcam-keyframes')","custom keyframe clipboard MIME survives Windows roundtrip");
      await second.CoreWebView2.ExecuteScriptAsync("editor.updatePlayhead(20);editor.scroll.focus();true");
      clipboardSequence=GetClipboardSequenceNumber();
      await Key(second.CoreWebView2,"c",67);
      TrackClipboard(clipboardSequence);
      string secondCopy=Forms.Clipboard.ContainsText()?Forms.Clipboard.GetText():"";
      if(!secondCopy.StartsWith("BlitzCamera keyframes\n"))throw new Exception("Native Ctrl+C did not preserve tagged clipboard");
      await Assert(second.CoreWebView2,"copies.length===1 && copies[0].trusted","native Ctrl+C still works with browser accelerator keys disabled");
      await second.CoreWebView2.ExecuteScriptAsync("editor.scroll.focus();true");
      await Key(second.CoreWebView2,"v",86);
      await Assert(second.CoreWebView2,"editor.doc.tracks.x.some(k=>k.time_sec===20 && k.value===17) && editor.doc.tracks.y.some(k=>k.time_sec===24 && k.value===27) && changes.length===2 && !notices.length","native Ctrl+C/V repeated keyframe paste");
      clipboardSequence=GetClipboardSequenceNumber();
      await first.CoreWebView2.ExecuteScriptAsync("document.getElementById('plain').focus();document.getElementById('plain').select();document.execCommand('copy');true");
      TrackClipboard(clipboardSequence);
      string plain=Forms.Clipboard.ContainsText()?Forms.Clipboard.GetText():"";
      if(plain!="BlitzCamera isolated native input")throw new Exception("Input copy was intercepted by timeline");
      Checks.Add("ordinary native input copy remains unchanged");
      await second.CoreWebView2.ExecuteScriptAsync("document.getElementById('plain').value='';document.getElementById('plain').focus();true");
      await Key(second.CoreWebView2,"v",86);
      await Assert(second.CoreWebView2,"document.getElementById('plain').value==='BlitzCamera isolated native input' && changes.length===2 && !notices.length","ordinary native input paste remains unchanged");
    }finally{first.Dispose();second.Dispose();window.Close();}
  }
  static async Task Navigate(CoreWebView2 web,string url){
    var completion=new TaskCompletionSource<bool>();
    EventHandler<CoreWebView2NavigationCompletedEventArgs> done=null;
    done=delegate(object sender,CoreWebView2NavigationCompletedEventArgs e){web.NavigationCompleted-=done;if(e.IsSuccess)completion.SetResult(true);else completion.SetException(new Exception("Navigation failed "+e.WebErrorStatus));};
    web.NavigationCompleted+=done;web.Navigate(url);await completion.Task;
  }
  static async Task Key(CoreWebView2 web,string key,int code){
    await web.CallDevToolsProtocolMethodAsync("Input.dispatchKeyEvent",Host.Json.Serialize(new{type="keyDown",key=key,code="Key"+key.ToUpperInvariant(),windowsVirtualKeyCode=code,nativeVirtualKeyCode=code,modifiers=2}));
    await web.CallDevToolsProtocolMethodAsync("Input.dispatchKeyEvent",Host.Json.Serialize(new{type="keyUp",key=key,code="Key"+key.ToUpperInvariant(),windowsVirtualKeyCode=code,nativeVirtualKeyCode=code,modifiers=2}));
    await Task.Delay(80);
  }
  static async Task Click(CoreWebView2 web,string selector){
    string result=await web.ExecuteScriptAsync("(()=>{const el=document.querySelector("+Host.Json.Serialize(selector)+");el.scrollIntoView();const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()");
    var point=Host.Json.Deserialize<Dictionary<string,object>>(result);
    foreach(string kind in new[]{"mousePressed","mouseReleased"})await web.CallDevToolsProtocolMethodAsync("Input.dispatchMouseEvent",Host.Json.Serialize(new{type=kind,x=Convert.ToDouble(point["x"]),y=Convert.ToDouble(point["y"]),button="left",clickCount=1}));
    await Task.Delay(80);
  }
  static async Task Assert(CoreWebView2 web,string expression,string name){
    string result=await web.ExecuteScriptAsync("!!("+expression+")");
    if(result!="true")throw new Exception(name+" failed; "+await web.ExecuteScriptAsync("JSON.stringify({ready:window.ready,notices,changes:changes.length,pastes,copies,data:editor.data(),active:document.activeElement.tagName})"));
    Checks.Add(name);
  }
}
