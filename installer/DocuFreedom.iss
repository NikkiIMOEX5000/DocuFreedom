; Inno Setup 6. Per-user installation; never requests administrator privileges.
#define AppVersion GetEnv("DOCUFREEDOM_VERSION")
#if AppVersion == ""
  #error DOCUFREEDOM_VERSION must be set by build-windows.ps1
#endif

[Setup]
AppId={{5780E144-891D-470E-9503-51D0A93D6147}
AppName=DocuFreedom
AppVersion={#AppVersion}
AppPublisher=dna.apps
AppPublisherURL=https://github.com/NikkiIMOEX5000/DocuFreedom
AppSupportURL=https://github.com/NikkiIMOEX5000/DocuFreedom/issues
AppUpdatesURL=https://github.com/NikkiIMOEX5000/DocuFreedom/releases
DefaultDirName={localappdata}\Programs\DocuFreedom
DefaultGroupName=DocuFreedom
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir=..\dist
OutputBaseFilename=DocuFreedom-{#AppVersion}-windows-x64-setup
SetupIconFile=..\build\DocuFreedom.ico
UninstallDisplayIcon={app}\DocuFreedom.exe
LicenseFile=..\LICENSE
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=DocuFreedom.exe
RestartApplications=no
UninstallDisplayName=DocuFreedom

[Tasks]
Name: "autostart"; Description: "Start DocuFreedom when I sign in to Windows"; Flags: unchecked
Name: "contextmenu"; Description: "Add DocuFreedom to the file context menu"; Flags: unchecked
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\DocuFreedom\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\DocuFreedom"; Filename: "{app}\DocuFreedom.exe"
Name: "{autodesktop}\DocuFreedom"; Filename: "{app}\DocuFreedom.exe"; Tasks: desktopicon
Name: "{usersendto}\DocuFreedom"; Filename: "{app}\DocuFreedom.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "DocuFreedom"; ValueData: """{app}\DocuFreedom.exe"" --quiet"; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\*\shell\DocuFreedom"; ValueType: string; ValueName: "MUIVerb"; ValueData: "DocuFreedom…"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\DocuFreedom"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\DocuFreedom.exe"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\DocuFreedom"; ValueType: string; ValueName: "MultiSelectModel"; ValueData: "Player"; Tasks: contextmenu
Root: HKCU; Subkey: "Software\Classes\*\shell\DocuFreedom\command"; ValueType: string; ValueName: ""; ValueData: """{app}\DocuFreedom.exe"" ""%1"""; Tasks: contextmenu

[Run]
Filename: "{app}\DocuFreedom.exe"; Description: "Launch DocuFreedom"; Flags: nowait postinstall skipifsilent

; No forceful taskkill on uninstall: Restart Manager asks the user to close the
; app, preserving unsaved edits. Preferences and document files are retained.
