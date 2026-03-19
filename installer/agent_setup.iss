; RKT Station Agent - Inno Setup Script
; Builds an installer for the RKT Station Agent
;
; Prerequisites:
;   1. Run: python build_agent.py
;   2. Install Inno Setup from https://jrsoftware.org/isinfo.php
;   3. Compile this script with Inno Setup

[Setup]
AppName=RKT Station Agent
AppVersion=1.3.0
AppPublisher=RKT Grading
AppPublisherURL=https://rktgradingstation.co.uk
DefaultDirName={autopf}\RKT Station Agent
DefaultGroupName=RKT Station Agent
OutputDir=..\dist
OutputBaseFilename=RKTStationAgent-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
SetupIconFile=compiler:SetupClassicIcon.ico
UninstallDisplayIcon={app}\RKTStationAgent.exe

[Files]
Source: "..\dist\RKTStationAgent.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\agent.env.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\rkt_agent.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "drivers\canon-lide400-driver.exe"; DestDir: "{app}\drivers"; Flags: ignoreversion

[Tasks]
Name: "startupentry"; Description: "Start automatically when Windows starts"; GroupDescription: "Startup:"; Flags: checkedonce
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "installdriver"; Description: "Install Canon LiDE 400 scanner driver"; GroupDescription: "Scanner:"; Flags: checkedonce

[Icons]
Name: "{group}\RKT Station Agent"; Filename: "{app}\RKTStationAgent.exe"; Parameters: "--tray"
Name: "{group}\Uninstall RKT Station Agent"; Filename: "{uninstallexe}"
Name: "{autodesktop}\RKT Station Agent"; Filename: "{app}\RKTStationAgent.exe"; Parameters: "--tray"; Tasks: desktopicon
Name: "{userstartup}\RKT Station Agent"; Filename: "{app}\RKTStationAgent.exe"; Parameters: "--tray"; Tasks: startupentry

[Run]
; Install Canon driver if selected
Filename: "{app}\drivers\canon-lide400-driver.exe"; Description: "Installing Canon LiDE 400 driver..."; StatusMsg: "Installing Canon scanner driver..."; Tasks: installdriver; Flags: waituntilterminated
; Launch the agent
Filename: "{app}\RKTStationAgent.exe"; Parameters: "--tray"; Description: "Launch RKT Station Agent"; Flags: nowait postinstall skipifsilent

[Code]
// Create default agent.env if it doesn't exist
procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvFile: String;
begin
  if CurStep = ssPostInstall then begin
    EnvFile := ExpandConstant('{app}\agent.env');
    if not FileExists(EnvFile) then begin
      FileCopy(ExpandConstant('{app}\agent.env.example'), EnvFile, True);
    end;
  end;
end;
