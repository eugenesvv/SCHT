#ifndef MyAppVersion
  #define MyAppVersion "1.6.0"
#endif

#define MyAppName "SCHT"
#define MyAppPublisher "SC Hauling Log Tracker"
#define MyAppExeName "SCHT.exe"

[Setup]
AppId={{2BDFDF69-F447-416E-9E80-D6368A46F0B0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\SCHT
DefaultGroupName=SCHT
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=SCHT-Setup-{#MyAppVersion}
SetupIconFile=..\assets\sc_hauling_logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AppMutex=Local\SC_Hauling_Log_Tracker_Desktop
SetupMutex=SCHT_Setup_Mutex
UsePreviousAppDir=yes
UsePreviousTasks=yes
ChangesAssociations=no
ChangesEnvironment=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\SCHT.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\SCHT"; Filename: "{app}\SCHT.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\SCHT"; Filename: "{app}\SCHT.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\SCHT.exe"; Description: "Launch SCHT"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; The user requested a trace-free app uninstall. Remove every SCHT-owned data
; directory, including the legacy folder used by development builds.
Type: filesandordirs; Name: "{localappdata}\SCHT"
Type: filesandordirs; Name: "{localappdata}\SC Hauling Log Tracker"
Type: filesandordirs; Name: "{app}"
