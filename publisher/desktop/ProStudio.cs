using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using Forms = System.Windows.Forms;

// Local files + stdin/stdout only. This host does not expose an HTTP service.
public sealed class ProStudio : Window
{
    const string Origin = "https://studio.blitzcamera.local/";
    readonly string root, data, smoke, smokeScript;
    readonly WebView2 web = new WebView2();
    readonly SemaphoreSlim queue = new SemaphoreSlim(1, 1);
    bool working;
    static JavaScriptSerializer Json() { return new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 }; }
    static string Quote(string value) { return "\"" + value.Replace("\"", "") .TrimEnd('\\') + "\""; }

    [STAThread]
    public static void Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string data = Path.Combine(root, "data"), smoke = null, script = null;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "--data" && i + 1 < args.Length) data = Path.GetFullPath(args[++i]);
            else if (args[i] == "--smoke" && i + 1 < args.Length) smoke = Path.GetFullPath(args[++i]);
            else if (args[i] == "--smoke-script" && i + 1 < args.Length) script = Path.GetFullPath(args[++i]);
        }
        string identity;
        using (var hash = System.Security.Cryptography.SHA256.Create()) identity = BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(data).ToLowerInvariant()))).Replace("-", "");
        bool created;
        using (var single = new Mutex(true, "Local\\BlitzCameraProStudio-" + identity, out created)) {
            if (!created) { MessageBox.Show("这个制作工具的数据目录已在另一个窗口打开。", "Pro Studio"); return; }
            try { new Application().Run(new ProStudio(root, data, smoke, script)); }
            finally { single.ReleaseMutex(); }
        }
    }

    ProStudio(string root, string data, string smoke, string smokeScript)
    {
        this.root = root; this.data = data; this.smoke = smoke; this.smokeScript = smokeScript;
        Title = "Blitz Camera Pro Studio"; Width = 1380; Height = 940; MinWidth = 940; MinHeight = 720;
        Background = new SolidColorBrush(Color.FromRgb(17, 18, 24)); Content = web;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        string icon = Path.Combine(root, "ProStudio.ico");
        if (File.Exists(icon)) Icon = new System.Windows.Media.Imaging.BitmapImage(new Uri(icon));
        if (smoke != null) { WindowStartupLocation = WindowStartupLocation.Manual; Left = -32000; Top = -32000; ShowActivated = false; ShowInTaskbar = false; }
        Closing += (sender, e) => { if (working) e.Cancel = true; };
        Loaded += async (sender, e) => await Start();
    }

    async Task Start()
    {
        try
        {
            Directory.CreateDirectory(data);
            var environment = await CoreWebView2Environment.CreateAsync(null, Path.Combine(data, "webview"));
            await web.EnsureCoreWebView2Async(environment);
            var core = web.CoreWebView2;
            core.Settings.AreDevToolsEnabled = false;
            core.Settings.AreDefaultContextMenusEnabled = false;
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;
            core.Settings.IsGeneralAutofillEnabled = false;
            core.SetVirtualHostNameToFolderMapping("studio.blitzcamera.local", Path.Combine(root, "app", "publisher", "web"), CoreWebView2HostResourceAccessKind.DenyCors);
            core.NavigationStarting += (sender, e) => { if (!e.Uri.StartsWith(Origin, StringComparison.Ordinal)) e.Cancel = true; };
            core.NewWindowRequested += (sender, e) => { e.Handled = true; };
            core.PermissionRequested += (sender, e) => { e.State = CoreWebView2PermissionState.Deny; };
            core.WebMessageReceived += async (sender, e) => await Receive(e);
            web.Source = new Uri(Origin + "index.html");
            if (smoke != null) await Smoke();
        }
        catch (Exception error)
        {
            if (smoke != null) { Directory.CreateDirectory(smoke); File.WriteAllText(Path.Combine(smoke, "error.txt"), error.ToString()); Environment.ExitCode = 1; Close(); }
            else { MessageBox.Show(this, "制作工具无法启动：\n" + error.Message + "\n请确认 Microsoft Edge WebView2 运行时可用。", Title, MessageBoxButton.OK, MessageBoxImage.Error); Close(); }
        }
    }

    async Task Receive(CoreWebView2WebMessageReceivedEventArgs e)
    {
        if (!e.Source.StartsWith(Origin, StringComparison.Ordinal)) return;
        object id = null;
        await queue.WaitAsync(); working = true;
        try
        {
            if (e.WebMessageAsJson.Length > 1024 * 1024) throw new InvalidOperationException("请求过大。");
            var request = Json().Deserialize<Dictionary<string, object>>(e.WebMessageAsJson);
            id = request["id"];
            string action = (string)request["action"];
            var value = request["value"] as Dictionary<string, object> ?? new Dictionary<string, object>();
            Dictionary<string, object> reply;
            if (action == "dialog") reply = new Dictionary<string, object> { { "ok", true }, { "result", Dialog(value) } };
            else if (action == "open_folder")
            {
                string path = Path.GetFullPath((string)value["path"]);
                if (!Directory.Exists(path)) throw new InvalidOperationException("输出文件夹不存在。");
                Process.Start(new ProcessStartInfo("explorer.exe", Quote(path)) { UseShellExecute = true });
                reply = new Dictionary<string, object> { { "ok", true }, { "result", true } };
            }
            else reply = await Backend(e.WebMessageAsJson);
            reply["id"] = id;
            web.CoreWebView2.PostWebMessageAsJson(Json().Serialize(reply));
        }
        catch (Exception error)
        {
            web.CoreWebView2.PostWebMessageAsJson(Json().Serialize(new { id = id, ok = false, error = error.Message }));
        }
        finally { working = false; queue.Release(); }
    }

    async Task<Dictionary<string, object>> Backend(string request)
    {
        var start = new ProcessStartInfo(Path.Combine(root, "runtime", "python.exe"),
            "-X utf8 -B -m publisher.rpc --data " + Quote(data) + " --defaults " + Quote(Path.Combine(root, "defaults.json"))) {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        using (var process = Process.Start(start))
        {
            var output = process.StandardOutput.ReadToEndAsync();
            var error = process.StandardError.ReadToEndAsync();
            byte[] bytes = Encoding.UTF8.GetBytes(request);
            await process.StandardInput.BaseStream.WriteAsync(bytes, 0, bytes.Length);
            process.StandardInput.Close();
            await Task.Run(() => process.WaitForExit());
            string text = await output, diagnostic = await error;
            if (process.ExitCode != 0) throw new InvalidOperationException("制作任务未完成。请检查运行目录和 Python 运行时。" + (String.IsNullOrEmpty(diagnostic) ? "" : "\n" + diagnostic.Substring(0, Math.Min(2000, diagnostic.Length))));
            return Json().Deserialize<Dictionary<string, object>>(text);
        }
    }

    object Dialog(Dictionary<string, object> value)
    {
        string kind = (string)value["kind"], initial = value.ContainsKey("initial") ? (string)value["initial"] : "";
        if (kind == "folder")
        {
            using (var dialog = new Forms.FolderBrowserDialog { Description = "选择升级包输出文件夹", SelectedPath = Directory.Exists(initial) ? initial : "" })
            {
                return dialog.ShowDialog(new DialogOwner(new System.Windows.Interop.WindowInteropHelper(this).Handle)) == Forms.DialogResult.OK ? (object)new { paths = new[] { dialog.SelectedPath } } : new { cancelled = true };
            }
        }
        bool save = kind == "save_master" || kind == "backup";
        string filter;
        switch (kind) {
            case "master": case "save_master": filter = "适配母包 (*.bcpro)|*.bcpro"; break;
            case "configs": filter = "用户配置 (*.bcconfig)|*.bcconfig"; break;
            case "recipe": case "trust": filter = "JSON 清单 (*.json)|*.json"; break;
            case "key": filter = "发布密钥 (*.dpapi)|*.dpapi"; break;
            case "backup": case "restore": filter = "加密密钥备份 (*.bcsecret)|*.bcsecret"; break;
            default: throw new InvalidOperationException("不支持的文件选择。");
        }
        Microsoft.Win32.FileDialog picker;
        if (save) picker = new Microsoft.Win32.SaveFileDialog { OverwritePrompt = true, AddExtension = true, DefaultExt = kind == "backup" ? ".bcsecret" : ".bcpro" };
        else picker = new Microsoft.Win32.OpenFileDialog { Multiselect = kind == "configs", CheckFileExists = true };
        picker.Filter = filter;
        if (!String.IsNullOrWhiteSpace(initial)) {
            if (Directory.Exists(initial)) picker.InitialDirectory = initial;
            else { string parent = Path.GetDirectoryName(initial); if (Directory.Exists(parent)) picker.InitialDirectory = parent; picker.FileName = Path.GetFileName(initial); }
        }
        return picker.ShowDialog(this) == true ? (object)new { paths = picker.FileNames } : new { cancelled = true };
    }

    sealed class DialogOwner : Forms.IWin32Window { public IntPtr Handle { get; private set; } public DialogOwner(IntPtr handle) { Handle = handle; } }

    async Task Smoke()
    {
        Directory.CreateDirectory(smoke);
        bool ready = false;
        for (int i = 0; i < 240; i++) {
            await Task.Delay(250);
            if (await web.ExecuteScriptAsync("document.body && document.body.dataset.ready === 'true'") == "true") { ready = true; break; }
        }
        if (!ready) throw new InvalidOperationException("制作界面初始化超时。");
        if (smokeScript != null) {
            await web.ExecuteScriptAsync(File.ReadAllText(smokeScript, Encoding.UTF8));
            bool done = false;
            for (int i = 0; i < 720; i++) {
                await Task.Delay(250);
                if (await web.ExecuteScriptAsync("!!window.__studioSmoke") == "true") { done = true; break; }
            }
            if (!done) throw new InvalidOperationException("制作工具交互检查超时。");
            string result = await web.ExecuteScriptAsync("window.__studioSmoke");
            File.WriteAllText(Path.Combine(smoke, "interaction.json"), result, Encoding.UTF8);
            if (result.Contains("\"error\"")) Environment.ExitCode = 1;
        }
        await Task.Delay(500);
        File.WriteAllText(Path.Combine(smoke, "state.json"), await web.ExecuteScriptAsync("({title:document.title,ready:document.body.dataset.ready,status:document.getElementById('status').textContent,version:document.getElementById('masterVersion').textContent,overflow:document.documentElement.scrollWidth>innerWidth})"), Encoding.UTF8);
        using (var stream = File.Create(Path.Combine(smoke, "window.png"))) await web.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, stream);
        Close();
    }
}
