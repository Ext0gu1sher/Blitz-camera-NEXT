// Portable entry point. Never opens a browser or accesses the game.
using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Net;
using System.Web.Script.Serialization;
using System.Windows.Forms;

class DesktopLauncher {
  [STAThread] static int Main(string[] args){
    string root=AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
    // Optional data root is used by isolated package verification only.
    string data=System.Environment.GetEnvironmentVariable("BLITZCAM_DATA_ROOT")??root;
    string key=BitConverter.ToString(SHA256.Create().ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(data).ToLowerInvariant()))).Replace("-","").Substring(0,24);
    bool created;
    using(var mutex=new Mutex(true,"Local\\BlitzCameraApp-"+key,out created)){
      if(!created){ShowExisting(data);return 0;}
      try{
        string python=Path.Combine(root,"runtime/pythonw.exe"),app=Path.Combine(root,"app");
        if(!File.Exists(python)||!Directory.Exists(app))throw new IOException("应用文件不完整，请先解压整个压缩包，再运行 BlitzCamera.exe。");
        var start=new ProcessStartInfo(python,"-X utf8 -B -m blitzcam.desktop.bootstrap") {UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=app};
        start.EnvironmentVariables["BLITZCAM_DATA_ROOT"]=Path.GetFullPath(data);
        using(var service=Process.Start(start)){
          service.WaitForExit();
          if(service.ExitCode!=0){
            if(System.Environment.GetEnvironmentVariable("BLITZCAM_DESKTOP_SMOKE")!="1")MessageBox.Show("启动未完成。请查看：\n"+Path.Combine(data,"output/desktop-service.log"),"Blitz Camera",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return service.ExitCode;
          }
        }
        return 0;
      }catch(Exception e){MessageBox.Show(e.Message,"Blitz Camera",MessageBoxButtons.OK,MessageBoxIcon.Error);return 2;}
      finally{mutex.ReleaseMutex();}
    }
  }
  static void ShowExisting(string root){
    try{
      var json=new JavaScriptSerializer();var state=json.DeserializeObject(File.ReadAllText(Path.Combine(root,"output/workstation-service.json"))) as System.Collections.Generic.Dictionary<string,object>;
      var uri=new Uri(Convert.ToString(state["url"]));
      if(uri.Scheme!="http"||uri.Host!="127.0.0.1"||uri.AbsolutePath!="/"||!string.IsNullOrEmpty(uri.UserInfo))return;
      var request=(HttpWebRequest)WebRequest.Create(new Uri(uri,"api/desktop/workbench"));request.Method="POST";request.ContentType="application/json";request.Timeout=3000;
      byte[] body=Encoding.UTF8.GetBytes("{}");request.ContentLength=body.Length;
      using(var stream=request.GetRequestStream())stream.Write(body,0,body.Length);
      using(var response=request.GetResponse()){}
    }catch{}
  }
}
