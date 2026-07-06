; Instalador do Escala do Carrinho (Parque das Nações)
; Compilar com: ISCC installer\setup.iss

#define MyAppName "Escala do Carrinho"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Congregação Parque das Nações"
#define MyAppExeName "EscalaCarrinho.exe"

[Setup]
AppId={{B4B6E6A0-6D9B-4B9C-9C8E-3C6E7F7B9A11}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; instala por-usuário, sem exigir admin — o app grava o banco de dados (data\carrinho.db)
; ao lado do .exe em runtime, então a pasta de instalação precisa ser gravável sem elevação.
DefaultDirName={localappdata}\Programs\EscalaCarrinho
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=EscalaCarrinho_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; some fields left for the user's data, offer removal but keep by default off — dados reais do carrinho
; ficam em {app}\data; o desinstalador padrão do Inno não remove arquivos criados após a instalação.
