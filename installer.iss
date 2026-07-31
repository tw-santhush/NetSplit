[Setup]
AppName=NetSplit
AppVersion=3.1.1
AppPublisher=Your Name
AppPublisherURL=https://github.com/tw-santhush/NetSplit
AppSupportURL=https://github.com/tw-santhush/NetSplit
DefaultDirName={pf}\NetSplit
DefaultGroupName=NetSplit
UninstallDisplayIcon={app}\icon.ico
Compression=lzma2
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=NetSplit_Setup
WizardStyle=modern
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\NetSplit\*"; DestDir: "{app}"; Flags: recursesubdirs
Source: "tools\*"; DestDir: "{app}\tools"; Flags: recursesubdirs
Source: "icon.ico"; DestDir: "{app}"
Source: "MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\NetSplit"; Filename: "{app}\NetSplit.exe"; IconFilename: "{app}\icon.ico"
Name: "{commondesktop}\NetSplit"; Filename: "{app}\NetSplit.exe"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Run]
; Install WebView2 if not already installed
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; \
    Parameters: "/silent /install"; \
    Check: WebView2NotInstalled; \
    Flags: runascurrentuser waituntilterminated
Filename: "{app}\NetSplit.exe"; Description: "Launch NetSplit"; Flags: postinstall nowait skipifsilent

[Code]
function WebView2NotInstalled: Boolean;
var
  ErrorCode: Integer;
begin
  // Check if WebView2 is installed via registry
  Result := not RegKeyExists(HKEY_LOCAL_MACHINE, 
    'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}');
end;
