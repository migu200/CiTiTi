# Colador CTT

Programa para o PC que:

1. recebe as fotos enviadas para o grupo de Telegram (através do bot);
2. lê os códigos de barras e QR codes de cada foto;
3. fica só com os códigos no formato **AA123456789AA** (ex.: `RR123456789PT`);
4. escreve cada código no campo da app Android e confirma-o, através do **ADB**;
5. responde no grupo a confirmar (✅ inserido, ↩️ repetido, ❌ erro, ⚠️ sem código válido).

Os códigos inseridos ficam registados em `codigos.csv`, que abre no Excel.

## 1. Ligar o telemóvel (ou o emulador) ao PC

### Telemóvel Android por USB
1. No telemóvel, ativa as **Opções de programador**: *Definições → Acerca do telefone* →
   toca 7 vezes em **Número de compilação**.
2. Em *Definições → Sistema → Opções de programador*, ativa a **Depuração USB**.
3. Liga o telemóvel ao PC por USB e aceita o pedido "Permitir depuração USB?". Marca a opção
   "Permitir sempre a partir deste computador".
4. Confirma a ligação: `platform-tools\adb.exe devices` deve mostrar o telemóvel como `device`.

### Telemóvel Android por Wi-Fi (Android 11 ou superior)
Ativa a **Depuração sem fios** nas Opções de programador e toca em
"Sincronizar dispositivo com código de sincronização". Depois, no PC:
```
platform-tools\adb.exe pair IP:PORTA_DE_SINCRONIZAÇÃO    (pede o código de 6 dígitos)
platform-tools\adb.exe connect IP:PORTA
```

### Emulador no PC
- **BlueStacks**: *Definições → Avançadas → Android Debug Bridge* → ativar. Depois
  `platform-tools\adb.exe connect 127.0.0.1:5555` (a porta aparece nessa mesma página).
- **LDPlayer**: a ligação ao ADB já vem ativa e o emulador aparece logo em `adb devices`.

## 2. Configurar onde escrever (`config.ini`)

O `config.ini` já tem o token do bot. Falta dizer ao programa **como confirmar o código na app**:

1. Abre a app no ecrã onde se escreve o código.
2. Testa: `iniciar.bat --testar-codigo RR123456789PT`
3. Vê o que aconteceu:
   - Se o código apareceu no campo e ficou confirmado, não precisas de mudar nada.
   - Se o texto não apareceu, preenche `campo_x`/`campo_y` com as coordenadas do campo.
   - Se o código apareceu mas não ficou confirmado, muda para `submeter = toque` e preenche
     `botao_x`/`botao_y` com as coordenadas do botão (ex.: "Adicionar").

**Como descobrir as coordenadas:** nas Opções de programador do telemóvel, ativa
**Localização do ponteiro**. Ao tocar no ecrã, aparecem os valores X e Y no topo.

Se a app limpar o campo sozinha depois de cada código, deixa `limpar_campo = nao`. Se não o
limpar, muda para `sim`.

## Login automático na MobiCTT

Antes de cada código, o programa lê o ecrã da app. Se a app estiver no ecrã de login, entra
sozinho com as credenciais guardadas.

```
iniciar.bat --guardar-login     # pede o utilizador e a password e guarda-os
iniciar.bat --testar-login      # se a app estiver no login, entra; depois mostra o ecrã atual
iniciar.bat --apagar-login      # apaga as credenciais
```

As credenciais ficam no **Gestor de Credenciais do Windows** (*Painel de Controlo → Gestor de
Credenciais → Credenciais do Windows → "colador-ctt-mobictt"*), cifradas e associadas à tua conta
do Windows. Não ficam em nenhum ficheiro do projeto e nunca aparecem no ecrã nem no registo.

Se o login pedir um código OTP, o programa não o consegue introduzir. Nesse caso, os códigos
ficam com erro e o grupo é avisado.

### Depois do login

1. **Selecionar a rota:** o programa nunca escolhe sozinho. Pergunta no grupo
   *"Qual rota devo escolher?"* e mostra um botão para cada rota. Escolhe a rota em que alguém
   tocar. Se ninguém responder em `espera_rota_minutos` (15 por omissão), os códigos dessa foto
   ficam com erro e a pergunta repete-se na foto seguinte.
2. **"Pretende iniciar o dia?":** o programa aceita sempre e avisa no grupo
   (*"▶️ Dia iniciado na MobiCTT (rota X)"*). Se aparecer o aviso da otimização da bateria,
   desliga-a.
3. **Viatura:** o programa toca no ícone do camião, escreve a matrícula da rota (secção
   `[viaturas]` do `config.ini`) e confirma. Depois avisa no grupo
   (*"🚚 Viatura 59-80-QE registada (rota 2775J)"*). Se a rota não tiver matrícula configurada,
   avisa que é preciso registá-la manualmente.

   | Rota  | Matrícula |
   |-------|-----------|
   | 2775I | 44-36-OU  |
   | 2775J | 59-80-QE  |
4. **Ecrã de inserção: só o EM ROTA.** O programa nunca usa a Atribuição, porque a atribuição é
   feita noutra máquina e chega a esta app por sincronização. Se o EM ROTA ainda não estiver
   disponível, o programa avisa no grupo e espera (`espera_disponivel_minutos`).
5. **Resposta da app:** depois de escrever cada código, o programa lê o aviso que a app mostra no
   topo do ecrã. Se a app disser *"O objeto lido não se encontra atribuído a um serviço"*, o
   código fica em espera: o programa volta a tentar de minuto a minuto durante
   `repetir_nao_atribuido_minutos` (30 por omissão), porque a atribuição pode ainda não ter
   sincronizado. Se mesmo assim falhar, responde ❌ no grupo. Outras recusas da app dão ❌ logo.


As fotos que chegam enquanto o programa espera pela escolha da rota ficam em fila e são tratadas
a seguir.

## 3. Pôr a funcionar

Faz duplo clique em **`iniciar.bat`**. Deixa a janela aberta e a app visível no telemóvel ou no
emulador, no ecrã onde se escreve o código. Para parar, carrega em Ctrl+C.

As fotos enviadas enquanto o programa está desligado ficam à espera **até 24 horas** e são
processadas quando o voltares a ligar.

## Códigos escritos à mão

Além das fotos, o programa lê os códigos escritos numa mensagem de texto ou na legenda de uma
foto (ex.: `DD551681788PT`, `dd 551681788 pt`, ou vários na mesma mensagem). As mensagens de texto
sem nenhum código são ignoradas, por isso o bot não responde a conversas normais.

## Limpar o histórico de códigos

- **No grupo:** envia `/limpar_historico`. O programa que está a correr esquece logo os códigos
  antigos e responde 🧹 no grupo.
- **No PC:** faz duplo clique em `limpar_historico.bat` (ou corre `iniciar.bat --limpar-historico`).
  Se o programa estiver a correr, reinicia-o depois.

O histórico nunca é apagado de vez: o ficheiro atual é guardado em
`historico_antigo/codigos_<data>.csv` e o programa começa um novo. Depois de limpar, os códigos
que já tinham sido inseridos podem voltar a ser inseridos.

## Testes úteis

```
iniciar.bat --so-ler                                 # responde no grupo com os códigos lidos, sem usar a app
iniciar.bat --testar-imagem C:\caminho\foto.jpg     # mostra os códigos que consegue ler
iniciar.bat --testar-codigo RR123456789PT            # escreve um código na app
```

## Cuidados

- **Não deixes o telemóvel bloquear nem mudar de ecrã.** O programa escreve no ecrã que estiver
  visível. Ativa "Manter ecrã ligado" nas Opções de programador (funciona com o carregador ligado).
- O programa não vê o ecrã da app. Se a app mostrar um erro ou um pop-up, os códigos seguintes
  podem ficar mal inseridos. Confirma de vez em quando, e vê o `codigos.csv` e as respostas no grupo.
- Cada bot só pode ser usado por um programa de cada vez. Não uses o mesmo token noutro sítio.
- Se uma foto comprimida não for lida, envia-a **como ficheiro**.
- Confirma que a utilização deste tipo de automatização na app de trabalho é permitida.

## Ficheiros

| Ficheiro | Para que serve |
|---|---|
| `colador.py` | O programa |
| `config.ini` | As tuas definições, incluindo o token. **Não partilhes este ficheiro.** |
| `config.exemplo.ini` | Modelo do `config.ini`, sem o token |
| `iniciar.bat` | Atalho para executar |
| `codigos.csv` | Histórico de códigos (criado automaticamente) |
| `estado.json` | Última mensagem processada (criado automaticamente) |
| `platform-tools/` | ADB (da Google) |
| `.venv/` | Python com as bibliotecas instaladas |
