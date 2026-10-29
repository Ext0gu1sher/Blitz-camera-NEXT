; Build through package_installer.py so only verified release files are included.
#ifndef PackageDir
  #error PackageDir is required
#endif
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef InstallerId
  #define InstallerId "BlitzCamera.Next"
#endif

[Setup]
AppId={#InstallerId}
AppName=Blitz Camera
AppVersion={#AppVersion}
AppVerName=Blitz Camera {#AppVersion}
AppPublisher=Blitz Camera
VersionInfoVersion=1.0.0.0
DefaultDirName={localappdata}\Programs\Blitz Camera
DefaultGroupName=Blitz Camera
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
UninstallDisplayIcon={app}\BlitzCamera.ico
SetupIconFile={#PackageDir}\BlitzCamera.ico
OutputDir={#OutputDir}
OutputBaseFilename=BlitzCamera-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "zhcn"; MessagesFile: "{#LanguageFile}"

[Messages]
ReadyLabel1=准备安装 Blitz Camera {#AppVersion}
ReadyLabel2a=点击“安装”即可完成。项目与设置会在升级和卸载时保留。缺少 WebView2 时将联网安装微软运行环境。

[Files]
#include PayloadList
Source: "{#Bootstrapper}"; Flags: dontcopy

[Icons]
Name: "{userprograms}\Blitz Camera"; Filename: "{app}\BlitzCamera.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\Blitz Camera"; Filename: "{app}\BlitzCamera.exe"; WorkingDir: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\Classes\.bcnproj\OpenWithProgids"; ValueType: none; ValueName: "BlitzCamera.Project"; Flags: uninsdeletevalue uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\.bcnproj"; ValueType: string; ValueName: ""; ValueData: "BlitzCamera.Project"; Flags: uninsdeletevalue uninsdeletekeyifempty; Check: CanSetDefaultAssociation
Root: HKCU; Subkey: "Software\Classes\BlitzCamera.Project"; ValueType: string; ValueName: ""; ValueData: "Blitz Camera 项目"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\BlitzCamera.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\BlitzCamera.ico"
Root: HKCU; Subkey: "Software\Classes\BlitzCamera.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\BlitzCamera.exe"" ""%1"""

[Run]
Filename: "{app}\BlitzCamera.exe"; Description: "启动 Blitz Camera"; Flags: nowait postinstall skipifsilent

[Code]
function CanSetDefaultAssociation: Boolean;
var Current: String;
begin
  Result := (not RegQueryStringValue(HKCU, 'Software\Classes\.bcnproj', '', Current)) or
    (Current = '') or (Current = 'BlitzCamera.Project');
end;

function HasWebView2: Boolean;
var Version: String;
begin
  Result := RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
  if not Result then
    Result := RegQueryStringValue(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function AppRunning: Boolean;
var Key: String;
begin
  Key := Uppercase(Copy(GetSHA256OfString(Utf8Encode(Lowercase(ExpandConstant('{app}')))), 1, 24));
  Result := CheckForMutexes('Local\BlitzCameraApp-' + Key);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Release: Cardinal; Code: Integer;
begin
  Result := '';
  if AppRunning then begin
    Result := '请保存项目并退出此目录中的 Blitz Camera，再点击重试。';
    exit;
  end;
  if (not RegQueryDWordValue(HKLM32, 'SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full', 'Release', Release)) or (Release < 394802) then begin
    Result := '请先安装 .NET Framework 4.6.2 或更高版本，然后重新运行安装包。';
    exit;
  end;
  if not HasWebView2 then begin
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then begin
      Result := 'WebView2 安装程序未能启动，请检查网络后重试。';
      exit;
    end;
    if not HasWebView2 then
      Result := 'WebView2 安装未完成（' + IntToStr(Code) + '）。请连接网络后重试，或先安装微软 WebView2 Runtime。';
  end;
end;

function InitializeUninstall: Boolean;
begin
  Result := not AppRunning;
  if not Result then
    MsgBox('请先保存项目并退出 Blitz Camera，再卸载。项目、设置和缓存会保留。', mbInformation, MB_OK);
end;
