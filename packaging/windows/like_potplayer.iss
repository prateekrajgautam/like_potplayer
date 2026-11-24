; Inno Setup 6.3+ script. Run through build-windows.ps1, which first generates build\windows\defines.iss and
; registry.iss (name, version, AppId GUID and the file-association registry entries) from the project's JSON.
#include "..\..\build\windows\defines.iss"
#define ExeName "like_potplayer.exe"

[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename={#AppName}-{#AppVersion}-setup
SetupIconFile=..\..\like_potplayer\assets\build\app.ico
UninstallDisplayIcon={app}\{#ExeName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; per-user install by default (no admin prompt); the wizard offers "for all users" if the user wants it
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ChangesAssociations=yes
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "assoc"; Description: "Open video and audio files with {#AppName} (double-click)"; GroupDescription: "File associations:"
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\like_potplayer\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#ExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#ExeName}"; Tasks: desktopicon

[Run]
; Windows 10/11 will not let an installer pick the default app silently: open the page where the user confirms it
Filename: "ms-settings:defaultapps"; Description: "Choose {#AppName} in Windows 'Default apps' (needed once)"; Flags: shellexec postinstall skipifsilent unchecked; Tasks: assoc
Filename: "{app}\{#ExeName}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

#include "..\..\build\windows\registry.iss"
