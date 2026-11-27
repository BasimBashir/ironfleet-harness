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
AppVersion=1.0.2
VersionInfoVersion=1.0.2
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
; Models for the local providers (public on ollama.com). thomson1-chat is NOT
; pulled: it is IronFleet's private build, never published - see ThomsonNote.
Filename: "{localappdata}\Programs\Ollama\ollama.exe"; Parameters: "pull bge-m3:567m"; Flags: runhidden waituntilterminated; StatusMsg: "Pulling the bge-m3 embedding model (~1.2 GB) - this can take several minutes..."; Check: OllamaPresent
Filename: "{localappdata}\Programs\Ollama\ollama.exe"; Parameters: "pull qwen3.8:27b"; Flags: runhidden waituntilterminated; StatusMsg: "Pulling the qwen3.8:27b local chat model (~17 GB) - this can take a long time..."; Check: OllamaPresent
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

function NotOllamaInstalled(): Boolean;
begin
  Result := not FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

function OllamaPresent(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

function HasModel(const name, tag: string): Boolean;
begin
  // shortcut: assumes the default model store; an OLLAMA_MODELS override reads as "missing" (over-asks for space)
  Result := FileExists(ExpandConstant('{%USERPROFILE}\.ollama\models\manifests\registry.ollama.ai\library\') + name + '\' + tag);
end;

// The 2026-11-17 Win11 tester had 0.9 GB free: the hidden model pulls ran out of
// disk and Setup looked hung. Refuse up front and say how much is needed.
function EnoughDisk(): Boolean;
var
  freeB, totalB: Int64;
  needGB, freeGB: Integer;
  parts, msg: string;
begin
  needGB := 2;                                   // IronFleet app incl. bin/ (~1 GB) + headroom
  parts := 'IronFleet app ~2 GB';
  if NotOllamaInstalled() then begin
    needGB := needGB + 6;                        // OllamaSetup download 1.9 GB + install 3.2 GB
    parts := parts + ', Ollama ~6 GB';
  end;
  if not HasModel('qwen3.8', '27b') then begin
    needGB := needGB + 17;
    parts := parts + ', qwen3.8:27b model ~17 GB';
  end;
  if not HasModel('bge-m3', '567m') then begin
    needGB := needGB + 2;
    parts := parts + ', bge-m3 model ~1.2 GB';
  end;
  Result := True;
  if not GetSpaceOnDisk64(ExpandConstant('{localappdata}'), freeB, totalB) then exit;
  freeGB := freeB div (1024 * 1024 * 1024);
  if freeGB < needGB then begin
    msg := Format('Not enough disk space to install IronFleet.' + #13#10#13#10 +
      'Required: about %d GB free on drive %s (%s).' + #13#10 +
      'Available: %d GB.' + #13#10#13#10 +
      'Please free at least %d GB and run Setup again.', [needGB,
      ExtractFileDrive(ExpandConstant('{localappdata}')), parts, freeGB, needGB - freeGB]);
    Log(msg);
    SuppressibleMsgBox(msg, mbCriticalError, MB_OK, IDOK);
    Result := False;
  end;
end;

function InitializeSetup(): Boolean;
var
  loc: string;
begin
  Result := EnoughDisk();
  if not Result then exit;
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

const
  ThomsonNote = 'About thomson1-chat: it is IronFleet''s private fine-tuned model and is not ' +
    'publicly downloadable, so Setup did not install it. Without it the "ollama-local" ' +
    'provider (extraction, classification, redaction) is unavailable. Open IronFleet > ' +
    'Model settings and set ollama-local''s model to qwen3.8:27b, or assign a cloud model. ' +
    'If your firm was given thomson1-chat, load it into Ollama yourself.';

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and not HasModel('thomson1-chat', 'latest') then
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10#13#10 + ThomsonNote;
end;
