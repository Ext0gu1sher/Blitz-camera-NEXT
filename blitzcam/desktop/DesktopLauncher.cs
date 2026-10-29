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
    string project=null;
    try{
      if(args.Length!=0){
        if(args.Length!=1)throw new IOException("请一次打开一个项目文件。");
        project=Path.GetFullPath(args[0]);
        string extension=Path.GetExtension(project).ToLowerInvariant();
        if((extension!=".bcnproj"&&extension!=".json")||!File.Exists(project))throw new IOException("请选择存在的 .bcnproj 或 .json 项目文件。");
      }
    }catch(Exception e){MessageBox.Show(e.Message,"Blitz Camera",MessageBoxButtons.OK,MessageBoxIcon.Error);return 2;}
    // Optional data root is used by isolated package verification only.
    string data=System.Environment.GetEnvironmentVariable("BLITZCAM_DATA_ROOT")??root;
    string key=BitConverter.ToString(SHA256.Create().ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(data).ToLowerInvariant()))).Replace("-","").Substring(0,24);
    bool created;
    using(var mutex=new Mutex(true,"Local\\BlitzCameraApp-"+key,out created)){
      if(!created)return ShowExisting(data,project)?0:2;
      try{
        string python=Path.Combine(root,"runtime/pythonw.exe"),app=Path.Combine(root,"app");
        string recovery=Path.Combine(root,"output/deployment/helper/run.py");
        if(File.Exists(recovery)&&File.Exists(Path.Combine(data,"output/deployment/transaction.json"))){
          var recover=new ProcessStartInfo(python,"-X utf8 -B \""+recovery+"\" --recover \""+root+"\" \""+Path.GetFullPath(data)+"\""){UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=root};
          using(var worker=Process.Start(recover)){worker.WaitForExit();if(worker.ExitCode!=0)throw new IOException("升级恢复未完成。原版本备份保留在 output/deployment/backups，请勿删除。");}
        }
        if(!File.Exists(python)||!Directory.Exists(app))throw new IOException("应用文件不完整，请先解压整个压缩包，再运行 BlitzCamera.exe。");
        var start=new ProcessStartInfo(python,"-X utf8 -B -m blitzcam.desktop.bootstrap"+(project==null?"":" --project \""+project+"\"")) {UseShellExecute=false,CreateNoWindow=true,WorkingDirectory=app};
        start.EnvironmentVariables["BLITZCAM_DATA_ROOT"]=Path.GetFullPath(data);
        start.EnvironmentVariables["BLITZCAM_INSTALL_ROOT"]=root;
        start.EnvironmentVariables["BLITZCAM_LAUNCHER_PID"]=Process.GetCurrentProcess().Id.ToString();
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
  static bool ShowExisting(string root,string project){
    for(int attempt=0;attempt<20;attempt++)try{
      var json=new JavaScriptSerializer();var state=json.DeserializeObject(File.ReadAllText(Path.Combine(root,"output/workstation-service.json"))) as System.Collections.Generic.Dictionary<string,object>;
      var uri=new Uri(Convert.ToString(state["url"]));
      if(uri.Scheme!="http"||uri.Host!="127.0.0.1"||uri.AbsolutePath!="/"||!string.IsNullOrEmpty(uri.UserInfo))throw new IOException("本机服务地址无效。");
      var request=(HttpWebRequest)WebRequest.Create(new Uri(uri,project==null?"api/desktop/workbench":"api/desktop/project"));request.Method="POST";request.ContentType="application/json";request.Timeout=3000;
      byte[] body=Encoding.UTF8.GetBytes(project==null?"{}":json.Serialize(new System.Collections.Generic.Dictionary<string,object>{{"path",project}}));request.ContentLength=body.Length;
      using(var stream=request.GetRequestStream())stream.Write(body,0,body.Length);
      using(var response=request.GetResponse()){}
      return true;
    }catch(WebException e){
      if(e.Response!=null){MessageBox.Show("项目未打开，请在工作台中重新选择有效项目。","Blitz Camera",MessageBoxButtons.OK,MessageBoxIcon.Error);return false;}
      Thread.Sleep(250);
    }catch{Thread.Sleep(250);}
    MessageBox.Show("工作台正在启动或暂时无法响应，请稍后再打开项目。","Blitz Camera",MessageBoxButtons.OK,MessageBoxIcon.Information);return false;
  }
}
