# CTT Scanner

App Android que recebe as imagens enviadas para um grupo de Telegram, lê os códigos de barras
e QR codes que essas imagens contêm e mostra o conteúdo numa lista (com opções para copiar,
partilhar e abrir links).

Tudo corre no telemóvel. A app usa um bot de Telegram para receber as imagens e o Google ML Kit
para ler os códigos. Não precisa de servidor.

## 1. Criar o bot de Telegram

1. No Telegram, abre o **@BotFather** e envia `/newbot`. Guarda o **token** que ele te dá.
2. Ainda no BotFather, envia `/setprivacy`, escolhe o bot e seleciona **Disable**.
   Sem isto, o bot não vê as fotos do grupo (só vê comandos).
3. Adiciona o bot ao grupo. Se já estava no grupo antes do passo 2, remove-o e volta a adicioná-lo.
   Em alternativa, torna o bot **administrador** do grupo.

## 2. Compilar o APK

### Com o Android Studio (recomendado)
1. Instala o [Android Studio](https://developer.android.com/studio).
2. Faz *File → Open* e escolhe esta pasta. Espera que o Gradle sincronize (a primeira vez demora).
3. *Build → Build App Bundle(s) / APK(s) → Build APK(s)*.
4. O APK fica em `app/build/outputs/apk/debug/app-debug.apk`.

### Pela linha de comandos
Com o Android SDK instalado (o Android Studio instala-o), na pasta do projeto:

```powershell
.\gradlew.bat assembleDebug     # APK de debug
.\gradlew.bat assembleRelease   # APK de release (assinado com a chave de debug)
```

Copia o APK para o telemóvel e instala-o. Tens de permitir "instalar apps de origem desconhecida".

## 3. Usar

1. Abre a app, toca em ⚙ e cola o token do bot.
2. A barra de estado mostra "Ligado como @nome_do_bot".
3. Envia para o grupo uma foto com um código de barras ou QR code. Em poucos segundos o código
   aparece na lista.
4. (Opcional) Para aceitar só um grupo, copia o ID que aparece na barra de estado
   (ex.: `-1001234567890`) para o campo "ID do grupo" nas definições.

## Filtro de códigos

A app só guarda códigos no formato **2 letras + 9 números + 2 letras** (ex.: `RR123456789PT`),
que é o formato dos números de registo dos CTT. Antes de verificar o formato, retira os espaços e
converte as letras para maiúsculas. A barra de estado indica quantos códigos foram ignorados em
cada imagem. Para mudar o formato, altera `TRACKING_CODE` em `MainViewModel.kt`.

## Limitações

- **A app só recebe imagens quando está aberta.** O Telegram guarda as mensagens que o bot ainda
  não leu durante **24 horas**. Se abrires a app dentro desse prazo, recebe as que ficaram para trás.
- O bot não vê mensagens enviadas **antes** de ter entrado no grupo.
- Só um programa pode ler as mensagens de cada bot. Se o mesmo token estiver em uso noutro sítio
  (outro telemóvel, um script ou um webhook), aparece um erro de "Conflito".
- As fotos enviadas normalmente são comprimidas pelo Telegram. Se um código pequeno não for lido,
  envia a imagem **como ficheiro** (sem compressão). A app também aceita imagens enviadas assim.
- O token do bot fica guardado no telemóvel. Quem tiver o APK **não** recebe o token, porque cada
  pessoa introduz o seu.

## Estrutura

| Ficheiro | Função |
|---|---|
| `TelegramClient.kt` | Chama a Bot API: `getMe`, `getUpdates` (long polling) e `getFile` para descarregar fotos |
| `BarcodeDecoder.kt` | Lê QR, EAN, Code 128, Data Matrix, PDF417 e outros formatos com o ML Kit |
| `ScanRepository.kt` | Guarda as definições e os códigos lidos (JSON no armazenamento interno) |
| `MainViewModel.kt` | Ciclo de receção: recebe imagens, descodifica, evita duplicados e trata erros |
| `MainActivity.kt` | Interface em Jetpack Compose: lista, definições, copiar, partilhar e apagar |
