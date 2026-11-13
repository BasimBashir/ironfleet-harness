; scripts/ironfleet-setup.iss - IronFleet Windows installer (Inno Setup 6.3+)
; Compile: "<ISCC> scripts\ironfleet-setup.iss"   (ISCC = Inno Setup Compiler)
;
; Packages dist\IronFleet (frozen app + data + web + bin), installs Ollama with
; its own setup exe when missing, then pulls the models the local providers
; point at - so the user installs, double-clicks, and everything is up.

#define AppName "IronFleet"
#define AppExe "IronFleet.exe"

[Setup]
AppId={{7C1F2E4A-9B36-4D58-8A21-54E3F0B6C9D2}
AppName={#AppName}
AppVersion=1.0
DefaultDirName={localappdata}\Programs\{#AppName}
PrivilegesRequired=lowest
SetupIconFile=ironfleet.ico
OutputDir=..\dist
OutputBaseFilename=IronFleet-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Files]
Source: "..\dist\IronFleet\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "https://ollama.com/download/OllamaSetup.exe"; DestName: "OllamaSetup.exe"; DestDir: "{tmp}"; ExternalSize: 1857663944; Flags: external download ignoreversion deleteafterinstall; Check: NotOllamaInstalled

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Run]
; Ollama via its own setup exe, silent, only when missing (downloaded at install time)
Filename: "{tmp}\OllamaSetup.exe"; Parameters: "/VERYSILENT /NORESTART"; Flags: runhidden waituntilterminated; StatusMsg: "Installing Ollama..."; Check: NotOllamaInstalled
; Models for the local providers. bge-m3 is public; the two chat models are
; custom builds - their pulls are attempted and tolerated to fail (exit codes
; are ignored in [Run]) where they are not published.
Filename: "{localappdata}\Programs\Ollama\ollama.exe"; Parameters: "pull bge-m3:567m"; Flags: runhidden waituntilterminated; StatusMsg: "Pulling the bge-m3 embedding model (~1.2 GB) - this can take several minutes..."; Check: OllamaPresent
Filename: "{localappdata}\Programs\Ollama\ollama.exe"; Parameters: "pull thomson1-chat:latest"; Flags: runhidden waituntilterminated; StatusMsg: "Pulling thomson1-chat (skipped where not published)..."; Check: OllamaPresent
Filename: "{localappdata}\Programs\Ollama\ollama.exe"; Parameters: "pull qwen3.8:27b"; Flags: runhidden waituntilterminated; StatusMsg: "Pulling qwen3.8:27b (skipped where not published)..."; Check: OllamaPresent
Filename: "{app}\{#AppExe}"; Description: "Launch IronFleet"; Flags: postinstall nowait skipifsilent

[Code]
// An install dir under %TEMP% (e.g. a leftover test install) must not pin the
// upgrade target: InitializeSetup forgets the remembered dir, InitializeWizard
// forces the default, and ssPostInstall removes the stale copy once the new
// install has succeeded.
const
  UninsKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C1F2E4A-9B36-4D58-8A21-54E3F0B6C9D2}_is1';

var
  OldLoc: string;

function UnderUserTemp(const dir: string): Boolean;
begin
  Result := Pos(LowerCase(ExpandConstant('{localappdata}') + '\temp\'),
                LowerCase(dir) + '\') = 1;
end;

function InitializeSetup(): Boolean;
var
  loc: string;
begin
  Result := True;
  OldLoc := '';
  if RegQueryStringValue(HKCU, UninsKey, 'InstallLocation', loc) and
     UnderUserTemp(loc) then
  begin
    OldLoc := loc;
    RegDeleteValue(HKCU, UninsKey, 'InstallLocation');
  end;
end;

procedure InitializeWizard();
begin
  if UnderUserTemp(WizardForm.DirEdit.Text) then
    WizardForm.DirEdit.Text := ExpandConstant('{localappdata}\Programs\{#AppName}');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (OldLoc <> '') and
     (CompareText(AddBackslash(OldLoc), AddBackslash(WizardDirValue)) <> 0) and
     FileExists(AddBackslash(OldLoc) + 'IronFleet.exe') then
    DelTree(OldLoc, True, True, True);
end;

function NotOllamaInstalled(): Boolean;
begin
  Result := not FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

function OllamaPresent(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;
