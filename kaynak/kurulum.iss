; Krersn IPTV - Windows kurulum betigi (Inno Setup 6)
; derle.ps1 bunu otomatik calistirir. Elle derlemek icin:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.1.0 kurulum.iss
;
; Kullanici klasorune kurar (yonetici izni sormaz). Ayarlar, giris bilgileri
; ve izleme gecmisi %USERPROFILE%\.iptv_panel klasorunde durur; kaldirma
; sirasinda silinmez.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef Kaynak
  #define Kaynak "dist\KrersnStudio"
#endif
#define AppName "Krersn IPTV"
#define AppExe "By Krersn Studio.exe"

[Setup]
; AppId degismemeli: yeni surumler eskisinin uzerine bu kimlikle kurulur.
AppId={{03A9C972-2B16-447F-9BFE-13CFCF52A1C8}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Krersn Studio
AppPublisherURL=https://krersnstudio.com
AppSupportURL=https://github.com/krersn/krersn-iptv
AppUpdatesURL=https://github.com/krersn/krersn-iptv/releases
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=kurulum
OutputBaseFilename=KrersnIPTV-Setup-v{#AppVersion}
SetupIconFile=krersn.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"

[Tasks]
Name: "masaustu"; Description: "Masaüstüne kısayol oluştur"; GroupDescription: "Ek seçenekler:"

[Files]
Source: "{#Kaynak}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Eski surumden kalan dosyalar yeni surumle karismasin.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} kaldır"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: masaustu

[Run]
Filename: "{app}\{#AppExe}"; Description: "{#AppName} uygulamasını başlat"; Flags: nowait postinstall skipifsilent
