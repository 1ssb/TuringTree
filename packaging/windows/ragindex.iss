; Inno Setup script for the RagIndex desktop app.
;
; Prerequisite: build the app first so dist\RagIndex\ exists —
;     python scripts\build_desktop.py
; Then open this file in Inno Setup (https://jrsoftware.org/isinfo.php) and click
; Compile, or from the command line:
;     iscc packaging\windows\ragindex.iss
;
; Output: dist\installer\RagIndex-Setup-<version>.exe — a per-user installer that
; needs NO administrator rights. The app stores its data under
; %LOCALAPPDATA%\RagIndex, so the install folder stays read-only at runtime.

#define MyAppName "RagIndex"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "RagIndex"
#define MyAppExeName "RagIndex.exe"

[Setup]
AppId={{8F2A7E3C-9B4D-4E1A-A6C2-7D5E1F0B3A9C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist\installer
OutputBaseFilename=RagIndex-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The entire PyInstaller output folder (executable + bundled UI, dataset, deps).
Source: "..\..\dist\RagIndex\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
