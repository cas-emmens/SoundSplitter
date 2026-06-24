; Inno Setup script for the self-contained SoundSplitter installer.
;
; We use Inno (not NSIS/Tauri's bundler) because the payload is >2GB and NSIS caps
; install data at ~2GB (32-bit offsets). Inno uses 64-bit LZMA2 and handles it.
; The app self-updates via a custom check in the Rust shell (see src-tauri/src/lib.rs)
; that downloads + minisign-verifies + runs this installer silently.
;
; Build with:  ISCC.exe /DAppVersion=0.1.0 sound-splitter.iss
; (build-installer.ps1 passes the version and signs the output.)

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "SoundSplitter"
#define AppExe "sound-splitter.exe"
; Stable AppId so updates upgrade the same install (do not change between releases).
#define AppId "{{9F3A6B2C-7E41-4C8B-9A2D-5E1F0B7C3D44}"

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Cas Emmens
VersionInfoVersion={#AppVersion}
WizardStyle=modern
; Per-user install, no admin rights required.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\SoundSplitter
DisableProgramGroupPage=yes
DefaultGroupName={#AppName}
; 64-bit only (the bundled Python/torch/Chromium are amd64).
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; >2GB payload: maximum solid LZMA2.
Compression=lzma2/max
SolidCompression=yes
; Close the running app during updates, then we relaunch it in [Run].
CloseApplications=yes
RestartApplications=no
SetupIconFile=src-tauri\icons\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=dist
OutputBaseFilename=SoundSplitter-Setup-{#AppVersion}

[Files]
; The Tauri shell executable.
Source: "src-tauri\target\release\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
; The full self-contained payload (Python runtime, Chromium, Tesseract, ffmpeg,
; Demucs weights, backend, built frontend). recursesubdirs pulls the whole tree.
Source: "src-tauri\payload\*"; DestDir: "{app}\payload"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
; Launch after install. No skipifsilent, so silent updates relaunch the app too.
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall
