"""Colador CTT

Recebe as fotos enviadas para um grupo de Telegram (através de um bot), lê os códigos de barras
e QR codes, fica só com os códigos no formato AA123456789AA (ex.: RR123456789PT) e escreve-os
numa app Android através do ADB.

Uso:
    python colador.py                        # funcionamento normal
    python colador.py --testar-codigo RR123456789PT   # só escreve este código na app
    python colador.py --testar-imagem foto.jpg        # só mostra os códigos lidos de uma imagem
"""

import argparse
import configparser
import csv
import getpass
import io
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import deque
from datetime import datetime
from pathlib import Path

import keyring
import keyring.errors
import requests
import zxingcpp
from PIL import Image, ImageOps

BASE = Path(__file__).resolve().parent
FICHEIRO_ESTADO = BASE / "estado.json"
FICHEIRO_HISTORICO = BASE / "codigos.csv"

# 2 letras + 9 números + 2 letras (ex.: RR123456789PT)
FORMATO_CODIGO = re.compile(r"^[A-Z]{2}[0-9]{9}[A-Z]{2}$")
LONG_POLL = 25

KEYCODE_BACK = 4
KEYCODE_ENTER = 66
KEYCODE_DEL = 67
KEYCODE_MOVE_END = 123


def log(texto):
    print(f"[{datetime.now():%H:%M:%S}] {texto}", flush=True)


# ---------------------------------------------------------------- configuração

class Config:
    def __init__(self, caminho):
        if not caminho.exists():
            sys.exit(f"Não encontrei {caminho.name}. Copia config.exemplo.ini para config.ini e preenche-o.")
        ini = configparser.ConfigParser()
        ini.BOOLEAN_STATES = {**ini.BOOLEAN_STATES, "sim": True, "s": True, "nao": False, "não": False, "n": False}
        ini.read(caminho, encoding="utf-8")

        self.token = ini.get("telegram", "token", fallback="").strip()
        grupo = ini.get("telegram", "grupo_id", fallback="").strip()
        self.grupo_id = int(grupo) if grupo else None
        self.responder_no_grupo = ini.getboolean("telegram", "responder_no_grupo", fallback=True)

        adb = ini.get("adb", "adb", fallback="platform-tools/adb.exe").strip()
        self.adb = str((BASE / adb).resolve()) if not Path(adb).is_absolute() else adb
        self.dispositivo = ini.get("adb", "dispositivo", fallback="").strip() or None

        self.campo_id = ini.get("app", "campo_id", fallback="").strip() or None
        self.campo = self._ponto(ini, "campo_x", "campo_y")
        self.limpar_campo = ini.getboolean("app", "limpar_campo", fallback=False)
        self.submeter = ini.get("app", "submeter", fallback="enter").strip().lower()
        self.botao_id = ini.get("app", "botao_id", fallback="").strip() or None
        self.botao = self._ponto(ini, "botao_x", "botao_y")
        self.pausa = ini.getfloat("app", "pausa_segundos", fallback=1.5)
        self.ignorar_repetidos = ini.getboolean("app", "ignorar_repetidos", fallback=True)
        self.login_automatico = ini.getboolean("app", "login_automatico", fallback=True)
        self.espera_rota_minutos = ini.getfloat("app", "espera_rota_minutos", fallback=15)
        # Elemento que só existe no ecrã de inserção (o campo do código também existe noutros ecrãs).
        self.ecra_id = ini.get("app", "ecra_id", fallback="").strip() or None
        # Botão do ecrã principal que abre o ecrã de inserção, e quanto tempo esperar que fique disponível.
        self.abrir_id = ini.get("app", "abrir_id", fallback="").strip() or None
        self.espera_disponivel_minutos = ini.getfloat("app", "espera_disponivel_minutos", fallback=60)
        # Durante quanto tempo repetir um código que a app diz ainda não estar atribuído à rota.
        self.repetir_nao_atribuido_minutos = ini.getfloat("app", "repetir_nao_atribuido_minutos", fallback=30)
        # Matrícula da viatura de cada rota, ex.: 2775J = 59-80-QE
        self.viaturas = {r.upper(): m.strip().upper() for r, m in ini.items("viaturas")} if ini.has_section("viaturas") else {}

        if self.submeter not in ("enter", "toque", "nada"):
            sys.exit("config.ini: 'submeter' tem de ser enter, toque ou nada.")
        if self.submeter == "toque" and not (self.botao or self.botao_id):
            sys.exit("config.ini: com submeter = toque tens de indicar botao_id ou botao_x/botao_y.")

    @staticmethod
    def _ponto(ini, kx, ky):
        x = ini.get("app", kx, fallback="").strip()
        y = ini.get("app", ky, fallback="").strip()
        return (int(x), int(y)) if x and y else None


# ---------------------------------------------------------------- ADB

class Adb:
    def __init__(self, exe, dispositivo):
        self.exe = exe
        self.dispositivo = dispositivo

    def _executar(self, *args):
        cmd = [self.exe] + (["-s", self.dispositivo] if self.dispositivo else []) + list(args)
        for tentativa in range(3):
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            erro = (r.stderr or "") + (r.stdout if r.returncode else "")
            perdido = "offline" in erro or "not found" in erro
            if not perdido or not self.dispositivo or ":" not in self.dispositivo:
                break
            # O emulador perdeu a ligação ao ADB: voltar a ligar e repetir.
            log("Ligação ao emulador perdida: a voltar a ligar…")
            subprocess.run([self.exe, "disconnect", self.dispositivo], capture_output=True, timeout=30)
            time.sleep(3 * (tentativa + 1))
            subprocess.run([self.exe, "connect", self.dispositivo], capture_output=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip() or f"adb terminou com código {r.returncode}")
        return r.stdout

    def verificar(self):
        if not Path(self.exe).exists():
            sys.exit(f"Não encontrei o adb em {self.exe}")
        if self.dispositivo and ":" in self.dispositivo:  # emulador/rede: (re)ligar
            subprocess.run([self.exe, "connect", self.dispositivo], capture_output=True, timeout=30)
        saida = subprocess.run([self.exe, "devices"], capture_output=True, text=True, timeout=30).stdout
        ligados = [l.split("\t")[0] for l in saida.splitlines()[1:] if l.endswith("\tdevice")]
        if not ligados:
            sys.exit("Nenhum telemóvel/emulador ligado ao ADB. Vê o README (secção 'Ligar o telemóvel').")
        if self.dispositivo and self.dispositivo not in ligados:
            sys.exit(f"O dispositivo {self.dispositivo} não está ligado. Ligados: {', '.join(ligados)}")
        if not self.dispositivo and len(ligados) > 1:
            sys.exit(f"Há vários dispositivos ligados ({', '.join(ligados)}). Indica qual em [adb] dispositivo.")
        log(f"ADB ligado a: {self.dispositivo or ligados[0]}")

    def tocar(self, ponto):
        self._executar("shell", "input", "tap", str(ponto[0]), str(ponto[1]))

    def escrever(self, texto):
        # "input text" não aceita espaços (usa %s) e o texto passa pela shell do Android.
        seguro = texto.replace(" ", "%s").replace("'", "'\\''")
        self._executar("shell", f"input text '{seguro}'")

    def teclas(self, *codigos):
        self._executar("shell", "input", "keyevent", *map(str, codigos))

    def elementos(self):
        """Elementos visíveis: lista de {"id", "texto", "centro"}.

        Nunca registar o resultado completo: o texto dos campos pode incluir a palavra-passe.
        """
        # Um cursor a piscar ou uma animação dão "could not get idle state": tentar de novo.
        for _ in range(8):
            saida = self._executar("exec-out", "uiautomator", "dump", "/dev/tty")
            inicio, fim = saida.find("<?xml"), saida.rfind(">")
            if inicio >= 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("não consegui ler o ecrã da app")
        lista = []
        for no in ET.fromstring(saida[inicio:fim + 1]).iter("node"):
            m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", no.get("bounds", ""))
            if m:
                x1, y1, x2, y2 = map(int, m.groups())
                lista.append({
                    "id": no.get("resource-id", "").split("/")[-1],
                    "texto": no.get("text", ""),
                    "centro": ((x1 + x2) // 2, (y1 + y2) // 2),
                })
        return lista

    def ecra(self):
        """Elementos com identificador (ex.: 'et_user') -> centro (x, y)."""
        ids = {}
        for e in self.elementos():
            if e["id"] and e["id"] not in ids:
                ids[e["id"]] = e["centro"]
        return ids


# ---------------------------------------------------------------- login na app

SERVICO_CREDENCIAIS = "colador-ctt-mobictt"
LOGIN_UTILIZADOR, LOGIN_PASSWORD, LOGIN_BOTAO = "et_user", "et_pass", "btn_access"


def guardar_login():
    print("As credenciais ficam no Gestor de Credenciais do Windows (cifradas), não em ficheiros.")
    utilizador = input("Utilizador da MobiCTT: ").strip()
    password = getpass.getpass("Password (não aparece ao escrever): ")
    if not utilizador or not password:
        sys.exit("Cancelado: utilizador e password são obrigatórios.")
    keyring.set_password(SERVICO_CREDENCIAIS, "utilizador", utilizador)
    keyring.set_password(SERVICO_CREDENCIAIS, "password", password)
    print("Credenciais guardadas.")


def apagar_login():
    for chave in ("utilizador", "password"):
        try:
            keyring.delete_password(SERVICO_CREDENCIAIS, chave)
        except keyring.errors.PasswordDeleteError:
            pass
    print("Credenciais apagadas.")


def preencher_campo(adb, ponto, texto):
    adb.tocar(ponto)
    time.sleep(0.3)
    adb.teclas(KEYCODE_MOVE_END, *[KEYCODE_DEL] * 40)
    adb.escrever(texto)
    time.sleep(0.3)


TITULO_ROTA, CANCELAR = "Selecionar a rota", "Cancelar"
INICIAR_DIA, ACEITAR = "Pretende iniciar o dia?", "Aceitar"


def opcoes_de_rota(elementos):
    """Se o diálogo "Selecionar a rota" estiver aberto, devolve {rota: centro}; senão None."""
    titulo = next((e for e in elementos if e["texto"] == TITULO_ROTA), None)
    if not titulo:
        return None
    y_cancelar = next((e["centro"][1] for e in elementos if e["texto"] == CANCELAR), 10 ** 6)
    return {e["texto"]: e["centro"] for e in elementos
            if e["texto"] and e["texto"] not in (TITULO_ROTA, CANCELAR)
            and titulo["centro"][1] < e["centro"][1] < y_cancelar}


def escolher_rota(adb, cfg, rotas, tg, chat_id):
    """Pergunta no grupo qual a rota (nunca escolhe sozinho) e toca na escolhida."""
    if tg is None or chat_id is None:
        raise RuntimeError("a app está a pedir a rota e não há grupo para perguntar")
    log(f"A app pede a rota ({', '.join(rotas)}): a perguntar no grupo…")
    resposta = tg.perguntar(
        chat_id, "🔐 Iniciei sessão na MobiCTT. Qual rota devo escolher?", list(rotas),
        cfg.espera_rota_minutos * 60,
    )
    if resposta is None:
        raise RuntimeError("ninguém escolheu a rota a tempo")
    rota, quem = resposta
    if rota == CANCELAR:
        raise RuntimeError(f"escolha da rota cancelada por {quem}")
    rotas_agora = opcoes_de_rota(adb.elementos())  # o diálogo pode ter mudado entretanto
    if not rotas_agora or rota not in rotas_agora:
        raise RuntimeError(f"a rota {rota} já não está disponível no ecrã")
    adb.tocar(rotas_agora[rota])
    log(f"Rota {rota} escolhida por {quem}.")
    time.sleep(3)


def aceitar_inicio_do_dia(adb, elementos, tg, chat_id):
    """Diálogo "Pretende iniciar o dia?": aceita sempre (decisão do utilizador) e avisa no grupo.

    Devolve a rota.
    """
    aceitar = next(e["centro"] for e in elementos if e["texto"] == ACEITAR)
    rota = next((e["texto"] for e in elementos if e["id"] == "tv_route_code"), "?")
    adb.tocar(aceitar)
    log(f"Dia iniciado na rota {rota}.")
    if tg and chat_id:
        tg.enviar(chat_id, f"▶️ Dia iniciado na MobiCTT (rota {rota}).")
    time.sleep(4)
    return rota


AVISO_BATERIA = "otimização da bateria"
PACOTE_APP = "com.rubricall.courier"


def tratar_aviso_bateria(adb, elementos):
    """Aviso "É necessário desligar a otimização da bateria": desliga-a pelo ADB e fecha o aviso."""
    adb._executar("shell", "dumpsys", "deviceidle", "whitelist", f"+{PACOTE_APP}")
    aceitar = next((e["centro"] for e in elementos if e["texto"] == ACEITAR), None)
    if aceitar:
        adb.tocar(aceitar)
        time.sleep(2)
    # O "Aceitar" abre as definições de bateria do Android: voltar à app.
    if "com.android.settings" in adb._executar("shell", "dumpsys window | grep mCurrentFocus"):
        adb.teclas(KEYCODE_BACK)
        time.sleep(2)
    log("Otimização da bateria desligada para a MobiCTT.")


# Ecrã "Telemetria" (ícone do camião): matrícula em 3 caixas "__ - __ - __", sem identificadores.
# As caixas são localizadas pelos dois traços entre elas. A app passa sozinha à caixa seguinte.
BOTAO_CONFIRMAR_VIATURA = (1014, 1854)  # botão ✓ que aparece depois de preencher (ecrã 1080x1920)


def registar_viatura(adb, cfg, rota, tg, chat_id):
    """Abre a Telemetria, escreve a matrícula da rota e confirma."""
    matricula = cfg.viaturas.get(rota.upper())

    def avisar(texto):
        log(texto)
        if tg and chat_id:
            tg.enviar(chat_id, texto)

    if not matricula:
        avisar(f"⚠️ Não tenho matrícula configurada para a rota {rota}. Regista a viatura manualmente.")
        return

    for _ in range(10):  # esperar pelo ecrã principal (com o ícone do camião)
        ecra = adb.ecra()
        if "menu_vehicle_selector" in ecra:
            break
        time.sleep(1.5)
    else:
        avisar(f"⚠️ Não encontrei o ícone da viatura. Regista a matrícula {matricula} manualmente.")
        return
    adb.tocar(ecra["menu_vehicle_selector"])
    time.sleep(3)

    elementos = adb.elementos()
    tracos = sorted((e["centro"] for e in elementos if e["texto"] == "-"), key=lambda c: c[0])
    if "Dados da Viatura" not in {e["texto"] for e in elementos} or len(tracos) < 2:
        avisar(f"⚠️ O ecrã da viatura não é o esperado. Regista a matrícula {matricula} manualmente.")
        return
    passo = tracos[1][0] - tracos[0][0]
    primeira_caixa = (tracos[0][0] - passo // 2, tracos[0][1])

    adb.tocar(primeira_caixa)
    time.sleep(1)
    for parte in matricula.split("-"):
        adb.escrever(parte)
        time.sleep(1.2)
    adb.tocar(BOTAO_CONFIRMAR_VIATURA)

    for _ in range(10):
        time.sleep(1.5)
        textos = {e["texto"] for e in adb.elementos()}
        if "Dados da Viatura" not in textos or any("sucesso" in t for t in textos):
            avisar(f"🚚 Viatura {matricula} registada (rota {rota}).")
            time.sleep(3)
            return
    avisar(f"⚠️ A matrícula {matricula} pode não ter ficado registada. Confirma na app.")


def garantir_app_a_frente(adb):
    """Se a MobiCTT não estiver no ecrã (ex.: alguém carregou em Início), abre-a."""
    for _ in range(3):
        if PACOTE_APP in adb._executar("shell", "dumpsys window | grep mCurrentFocus"):
            return
        log("A MobiCTT não está no ecrã: a abri-la…")
        adb._executar("shell", "monkey", "-p", PACOTE_APP, "-c", "android.intent.category.LAUNCHER", "1")
        time.sleep(5)
    raise RuntimeError("não consegui pôr a MobiCTT no ecrã")


def garantir_sessao(adb, cfg, tg=None, chat_id=None):
    """Garante que a app tem sessão iniciada, rota escolhida e dia iniciado. Devolve o ecrã atual (ids)."""
    garantir_app_a_frente(adb)
    for _ in range(6):  # login -> rota -> iniciar o dia -> (ecrã principal)
        elementos = adb.elementos()
        rotas = opcoes_de_rota(elementos)
        if rotas:
            escolher_rota(adb, cfg, rotas, tg, chat_id)
            continue
        textos = {e["texto"] for e in elementos}
        if any(AVISO_BATERIA in t for t in textos):
            tratar_aviso_bateria(adb, elementos)
            continue
        if INICIAR_DIA in textos and ACEITAR in textos:
            rota = aceitar_inicio_do_dia(adb, elementos, tg, chat_id)
            for _ in range(5):  # o aviso da bateria pode aparecer logo a seguir
                elementos = adb.elementos()
                if not any(AVISO_BATERIA in e["texto"] for e in elementos):
                    break
                tratar_aviso_bateria(adb, elementos)
            registar_viatura(adb, cfg, rota, tg, chat_id)
            continue
        ids = {e["id"]: e["centro"] for e in reversed(elementos) if e["id"]}
        if LOGIN_UTILIZADOR in ids:
            fazer_login(adb, cfg, ids)
            continue
        return ids
    raise RuntimeError("a app não chegou ao ecrã principal depois do login")


def fazer_login(adb, cfg, ecra):
    if not cfg.login_automatico:
        raise RuntimeError("a app está no ecrã de login")
    utilizador = keyring.get_password(SERVICO_CREDENCIAIS, "utilizador")
    password = keyring.get_password(SERVICO_CREDENCIAIS, "password")
    if not utilizador or not password:
        raise RuntimeError("a app está no ecrã de login e não há credenciais guardadas (iniciar.bat --guardar-login)")

    log("A app está no ecrã de login: a iniciar sessão…")
    preencher_campo(adb, ecra[LOGIN_UTILIZADOR], utilizador)
    preencher_campo(adb, adb.ecra()[LOGIN_PASSWORD], password)
    adb.tocar(adb.ecra()[LOGIN_BOTAO])
    for _ in range(20):
        time.sleep(1.5)
        if LOGIN_UTILIZADOR not in adb.ecra():
            log("Sessão iniciada.")
            return
    raise RuntimeError("o login não ficou concluído (password errada, código OTP ou erro da app)")


def no_ecra_de_insercao(cfg, ecra):
    return cfg.campo_id in ecra and (not cfg.ecra_id or cfg.ecra_id in ecra)


def abrir_ecra_de_insercao(adb, cfg, botao, tg, chat_id):
    """No ecrã principal, toca no botão do ecrã de inserção (ex.: EM ROTA).

    Se o botão ainda não estiver disponível (o toque não muda de ecrã), avisa no grupo e espera.
    """
    limite = time.time() + cfg.espera_disponivel_minutos * 60
    avisado = False
    while True:
        log(f"A abrir o ecrã de inserção ({cfg.abrir_id})…")
        adb.tocar(botao)
        time.sleep(3)
        ecra = adb.ecra()
        if cfg.abrir_id not in ecra:  # saiu do ecrã principal
            if avisado and tg and chat_id:
                tg.enviar(chat_id, "▶️ O ecrã de inserção já está disponível. A continuar.")
            return ecra
        if time.time() > limite:
            raise RuntimeError("o ecrã de inserção (EM ROTA) não ficou disponível a tempo")
        if not avisado:
            log("O ecrã de inserção ainda não está disponível: à espera…")
            if tg and chat_id:
                tg.enviar(chat_id, "⏳ O EM ROTA ainda não está disponível na MobiCTT. "
                                   "Os códigos ficam à espera e são inseridos quando ficar.")
            avisado = True
        time.sleep(30)
        botao = ecra[cfg.abrir_id]


EM_ENTREGA = "a app está numa entrega em curso"
ID_ECRA_ENTREGA = "tv_read_services_count"  # só existe no ecrã "Entrega"


def ir_para_insercao(adb, cfg, ecra, tg=None, chat_id=None):
    """Leva a app até ao ecrã de inserção, em modo Manual. Devolve o ecrã atual."""
    for _ in range(5):
        if no_ecra_de_insercao(cfg, ecra):
            return ecra
        if ID_ECRA_ENTREGA in ecra:
            # Nunca sair de uma entrega (a app suspenderia o serviço): esperar que alguém a termine.
            raise RuntimeError(EM_ENTREGA)
        if cfg.abrir_id and cfg.abrir_id in ecra:  # ecrã principal
            ecra = abrir_ecra_de_insercao(adb, cfg, ecra[cfg.abrir_id], tg, chat_id)
            continue
        if cfg.ecra_id and cfg.ecra_id in ecra and "scanner_selector" in ecra:
            # Ecrã certo, mas o scanner não está em modo Manual (não há campo de texto).
            log("A mudar o scanner para Manual…")
            adb.tocar(ecra["scanner_selector"])
            time.sleep(1.5)
            manual = next((e["centro"] for e in adb.elementos() if e["texto"] == "Manual"), None)
            if not manual:
                break
            adb.tocar(manual)
        else:
            # Noutro ecrã da app (ex.: Atribuição, Telemetria): voltar atrás.
            adb.teclas(KEYCODE_BACK)
        time.sleep(3)
        ecra = adb.ecra()
    return ecra


def inserir_na_app(adb, cfg, codigo, tg=None, chat_id=None):
    ecra = garantir_sessao(adb, cfg, tg, chat_id)

    if cfg.campo_id:
        if not no_ecra_de_insercao(cfg, ecra):
            ecra = ir_para_insercao(adb, cfg, ecra, tg, chat_id)
        if not no_ecra_de_insercao(cfg, ecra):
            raise RuntimeError("a app não está no ecrã de inserção de códigos")
        adb.tocar(ecra[cfg.campo_id])
        time.sleep(0.4)
    elif cfg.campo:
        adb.tocar(cfg.campo)
        time.sleep(0.4)
    if cfg.limpar_campo:
        adb.teclas(KEYCODE_MOVE_END, *[KEYCODE_DEL] * 30)
    adb.escrever(codigo)
    time.sleep(0.3)

    # A MobiCTT aceita o código sozinha quando ele fica completo (o campo esvazia-se).
    # Só se o código continuar no campo é que é preciso confirmar.
    elementos = adb.elementos()
    mensagem = mensagem_da_app(elementos)
    ainda_no_campo = any(e["id"] == cfg.campo_id and codigo in e["texto"] for e in elementos)
    if ainda_no_campo and not mensagem:
        if cfg.submeter == "enter":
            adb.teclas(KEYCODE_ENTER)
        elif cfg.submeter == "toque":
            botao = dict((e["id"], e["centro"]) for e in elementos if e["id"]).get(cfg.botao_id) \
                if cfg.botao_id else cfg.botao
            if not botao:
                raise RuntimeError("não encontrei o botão de confirmar no ecrã")
            adb.tocar(botao)
        time.sleep(0.5)
        mensagem = mensagem_da_app(adb.elementos())

    if mensagem and PALAVRAS_DE_ERRO.search(mensagem):
        raise RuntimeError(f"a app recusou: {mensagem}")
    time.sleep(cfg.pausa)  # dá tempo à app para processar antes do próximo código
    return mensagem, ler_morada(adb)


def ler_morada(adb):
    """Depois de um código aceite, a app abre o ecrã "Entrega" com a morada da paragem."""
    for _ in range(6):
        ids = {e["id"]: e["texto"] for e in adb.elementos() if e["id"]}
        # "tv_read_services_count" só existe no ecrã Entrega (a lista do Em rota também tem moradas).
        if "tv_read_services_count" in ids and ids.get("tv_address"):
            return resumir_morada(ids["tv_address"])
        time.sleep(0.7)
    return None


CODIGO_POSTAL = re.compile(r"(?<!\d)(\d{4})\s*-\s*(\d{3})(?!\d)")


def resumir_morada(morada):
    """Da morada completa fica só o código postal + "portugal" (ex.: "2775-305 portugal").

    Se não houver código postal, devolve a morada completa.
    """
    encontrados = CODIGO_POSTAL.findall(morada)
    if encontrados:
        quatro, tres = encontrados[-1]  # o último é o da localidade (vem no fim da morada)
        return f"{quatro}-{tres} portugal"
    return " ".join(morada.split())


# Avisos da MobiCTT: faixa no topo do ecrã (por cima da barra de título), sem identificador.
TEXTOS_DA_BARRA = {"Em rota", "Atribuição", "Telemetria", "CTT", "SELECIONAR O SCANNER"}
PALAVRAS_DE_ERRO = re.compile(r"\bnão\b|erro|inválid|inexistente|já foi|falh", re.IGNORECASE)


def mensagem_da_app(elementos):
    """Texto do aviso que a app mostra no topo depois de ler um código, ou None."""
    for e in elementos:
        texto = e["texto"].strip()
        if (texto and e["centro"][1] < 132 and not e["id"]
                and texto not in TEXTOS_DA_BARRA and not texto.startswith("Versão")):
            return texto
    return None


# ---------------------------------------------------------------- Telegram

class Telegram:
    def __init__(self, token):
        self.token = token
        self.api = f"https://api.telegram.org/bot{token}"
        self.ficheiros = f"https://api.telegram.org/file/bot{token}"
        self.sessao = requests.Session()
        self.offset = 0
        # Atualizações recebidas e ainda não processadas (ex.: fotos que chegam enquanto se
        # espera pela escolha da rota).
        self.fila = deque()

    def _pedido(self, url, **kwargs):
        try:
            r = self.sessao.post(url, **kwargs)
        except requests.RequestException as e:
            # Não deixar o token aparecer nas mensagens de erro.
            raise RuntimeError(str(e).replace(self.token, "***")) from None
        return r

    def chamar(self, metodo, params=None, espera=30):
        dados = self._pedido(f"{self.api}/{metodo}", json=params or {}, timeout=espera).json()
        if not dados.get("ok"):
            codigo = dados.get("error_code")
            descricao = dados.get("description", "erro desconhecido")
            if codigo in (401, 404):
                sys.exit("Token do bot inválido. Verifica o config.ini.")
            if codigo == 409:
                descricao += " (o bot está a ser usado por outro programa/app ao mesmo tempo)"
            raise RuntimeError(descricao)
        return dados["result"]

    def receber(self, espera=LONG_POLL):
        """Novas atualizações desde a última chamada (long polling)."""
        novas = self.chamar(
            "getUpdates",
            {"offset": self.offset, "timeout": espera,
             "allowed_updates": ["message", "channel_post", "callback_query"]},
            espera=espera + 15,
        )
        if novas:
            self.offset = novas[-1]["update_id"] + 1
        return novas

    def perguntar(self, chat_id, texto, opcoes, espera_segundos):
        """Envia uma pergunta com botões e espera que alguém toque num.

        Devolve (opção, nome de quem escolheu), ou None se ninguém responder a tempo.
        As outras mensagens que chegarem entretanto ficam na fila para depois.
        """
        botoes = [[{"text": o, "callback_data": f"op:{i}"}] for i, o in enumerate(opcoes)]
        botoes.append([{"text": CANCELAR, "callback_data": "op:cancelar"}])
        pergunta = self.chamar("sendMessage", {
            "chat_id": chat_id, "text": texto, "reply_markup": {"inline_keyboard": botoes},
        })
        limite = time.time() + espera_segundos
        while time.time() < limite:
            try:
                novas = self.receber(espera=min(LONG_POLL, max(1, int(limite - time.time()))))
            except RuntimeError as e:
                log(f"Erro no Telegram: {e}. Nova tentativa em 5 s…")
                time.sleep(5)
                continue
            for upd in novas:
                cq = upd.get("callback_query")
                if not cq or cq.get("message", {}).get("message_id") != pergunta["message_id"]:
                    self.fila.append(upd)
                    continue
                quem = cq.get("from", {}).get("first_name", "?")
                escolha = cq.get("data", "").removeprefix("op:")
                opcao = CANCELAR if escolha == "cancelar" else opcoes[int(escolha)]
                self._fechar_pergunta(pergunta, cq["id"], f"{texto}\n➡️ {opcao} (escolhido por {quem})")
                return opcao, quem
        self._fechar_pergunta(pergunta, None, f"{texto}\n⌛ Sem resposta a tempo.")
        return None

    def _fechar_pergunta(self, pergunta, callback_id, texto_final):
        try:
            if callback_id:
                self.chamar("answerCallbackQuery", {"callback_query_id": callback_id})
            self.chamar("editMessageText", {
                "chat_id": pergunta["chat"]["id"], "message_id": pergunta["message_id"], "text": texto_final,
            })
        except Exception as e:
            log(f"Aviso: não consegui atualizar a pergunta no grupo ({e})")

    def descarregar(self, file_id):
        caminho = self.chamar("getFile", {"file_id": file_id})["file_path"]
        try:
            r = self.sessao.get(f"{self.ficheiros}/{caminho}", timeout=60)
        except requests.RequestException as e:
            raise RuntimeError(str(e).replace(self.token, "***")) from None
        r.raise_for_status()
        return r.content

    def enviar(self, chat_id, texto):
        try:
            self.chamar("sendMessage", {"chat_id": chat_id, "text": texto})
        except Exception as e:
            log(f"Aviso: não consegui enviar mensagem para o grupo ({e})")

    def responder(self, chat_id, message_id, texto):
        try:
            self.chamar("sendMessage", {
                "chat_id": chat_id,
                "text": texto,
                "reply_parameters": {"message_id": message_id, "allow_sending_without_reply": True},
            })
        except Exception as e:
            log(f"Aviso: não consegui responder no grupo ({e})")


def extrair_imagem(mensagem):
    """Devolve o file_id da imagem da mensagem, ou None."""
    fotos = mensagem.get("photo")
    if fotos:
        return fotos[-1]["file_id"]  # o último tamanho é o maior
    doc = mensagem.get("document")
    if doc and doc.get("mime_type", "").startswith("image/"):
        return doc["file_id"]  # imagem enviada como ficheiro (sem compressão)
    return None


def nome_remetente(mensagem):
    de = mensagem.get("from")
    if de:
        nome = " ".join(p for p in (de.get("first_name"), de.get("last_name")) if p)
        return nome or de.get("username", "?")
    return mensagem.get("sender_chat", {}).get("title", "?")


# ---------------------------------------------------------------- leitura de códigos

def ler_codigos(dados):
    """Devolve (códigos válidos, número total de códigos lidos na imagem)."""
    imagem = ImageOps.exif_transpose(Image.open(io.BytesIO(dados))).convert("RGB")
    lidos = [r.text for r in zxingcpp.read_barcodes(imagem)]
    validos = []
    for texto in lidos:
        codigo = re.sub(r"\s", "", texto).upper()
        if FORMATO_CODIGO.match(codigo) and codigo not in validos:
            validos.append(codigo)
    return validos, len(lidos)


# ---------------------------------------------------------------- estado e histórico

def carregar_offset():
    try:
        return json.loads(FICHEIRO_ESTADO.read_text(encoding="utf-8"))["offset"]
    except (FileNotFoundError, KeyError, ValueError):
        return 0


def guardar_offset(offset):
    FICHEIRO_ESTADO.write_text(json.dumps({"offset": offset}), encoding="utf-8")


def carregar_inseridos():
    if not FICHEIRO_HISTORICO.exists():
        return set()
    with FICHEIRO_HISTORICO.open(encoding="utf-8-sig", newline="") as f:
        return {linha["codigo"] for linha in csv.DictReader(f, delimiter=";") if linha["estado"] == "inserido"}


def limpar_historico():
    """Começa um histórico novo. O atual não é apagado: fica numa cópia em historico_antigo/.

    Devolve o caminho da cópia, ou None se não havia histórico.
    """
    if not FICHEIRO_HISTORICO.exists():
        return None
    pasta = FICHEIRO_HISTORICO.parent / "historico_antigo"
    pasta.mkdir(exist_ok=True)
    copia = pasta / f"codigos_{datetime.now():%Y-%m-%d_%H%M%S}.csv"
    FICHEIRO_HISTORICO.replace(copia)
    return copia


COMANDO_LIMPAR = re.compile(r"^/limpar_historico(@\w+)?\s*$", re.IGNORECASE)


def registar(codigo, estado, grupo, remetente):
    novo = not FICHEIRO_HISTORICO.exists()
    with FICHEIRO_HISTORICO.open("a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        if novo:
            w.writerow(["data", "codigo", "estado", "grupo", "remetente"])
        w.writerow([f"{datetime.now():%Y-%m-%d %H:%M:%S}", codigo, estado, grupo, remetente])


# ---------------------------------------------------------------- ciclo principal

NAO_ATRIBUIDO = "não se encontra atribuído"
INTERVALO_PENDENTES = 60  # segundos entre tentativas de um código em espera


def motivo_de_espera(erro, cfg):
    """Se o erro for passageiro, devolve (minutos máximos de espera, texto para o grupo); senão None."""
    if NAO_ATRIBUIDO in erro and cfg.repetir_nao_atribuido_minutos > 0:
        return (cfg.repetir_nao_atribuido_minutos,
                f"ainda não está atribuído à rota. Volto a tentar de minuto a minuto "
                f"durante {cfg.repetir_nao_atribuido_minutos:g} min.")
    if EM_ENTREGA in erro:
        return (cfg.espera_disponivel_minutos,
                "a app está numa entrega em curso. Insiro-o quando a app voltar ao Em rota.")
    return None


def tentar_pendentes(tg, adb, cfg, inseridos, pendentes):
    """Volta a tentar os códigos que a app recusou por ainda não estarem atribuídos à rota
    (a atribuição é feita noutra máquina e chega à app por sincronização)."""
    agora = time.time()
    for p in [p for p in pendentes if p["proxima"] <= agora]:
        codigo = p["codigo"]
        try:
            mensagem, morada = inserir_na_app(adb, cfg, codigo, tg, p["chat_id"])
        except Exception as e:
            motivo = motivo_de_espera(str(e), cfg)
            if motivo and agora - p["inicio"] <= motivo[0] * 60:
                p["proxima"] = time.time() + INTERVALO_PENDENTES
                continue
            pendentes.remove(p)
            log(f"  {codigo}: desisti ({e})")
            registar(codigo, "erro", p["grupo"], p["remetente"])
            tg.responder(p["chat_id"], p["message_id"], f"❌ Erro ao inserir: {codigo} ({e})")
            continue
        pendentes.remove(p)
        log(f"  {codigo}: inserido na app depois de esperar pela atribuição")
        registar(codigo, "inserido", p["grupo"], p["remetente"])
        inseridos.add(codigo)
        tg.responder(p["chat_id"], p["message_id"], texto_inserido(codigo, mensagem, morada))


def texto_inserido(codigo, mensagem, morada):
    texto = f"✅ Inserido: {codigo}" + (f" ({mensagem})" if mensagem else "")
    return texto + (f"\n📍 {morada}" if morada else "")


CODIGO_NO_TEXTO = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{2}\s?\d{9}\s?[A-Za-z]{2}(?![A-Za-z0-9])")


def codigos_no_texto(texto):
    """Códigos AA123456789AA escritos numa mensagem ou legenda (aceita minúsculas e espaços)."""
    codigos = []
    for bruto in CODIGO_NO_TEXTO.findall(texto or ""):
        codigo = re.sub(r"\s", "", bruto).upper()
        if FORMATO_CODIGO.match(codigo) and codigo not in codigos:
            codigos.append(codigo)
    return codigos


def processar_mensagem(msg, tg, adb, cfg, inseridos, pendentes=None):
    file_id = extrair_imagem(msg)
    escritos = codigos_no_texto(msg.get("text") or msg.get("caption"))
    if not file_id and not escritos:
        return  # mensagem sem imagem nem códigos escritos: ignorar
    chat = msg["chat"]
    if cfg.grupo_id is not None and chat["id"] != cfg.grupo_id:
        return

    grupo = chat.get("title") or chat.get("first_name") or "privado"
    remetente = nome_remetente(msg)
    log(f"{'Imagem' if file_id else 'Mensagem'} de {remetente} em '{grupo}' (ID do grupo: {chat['id']})")

    codigos, total = ler_codigos(tg.descarregar(file_id)) if file_id else ([], 0)
    codigos += [c for c in escritos if c not in codigos]
    if not codigos:
        aviso = ("Nenhum código encontrado na imagem." if total == 0 else
                 f"{total} código(s) lido(s), mas nenhum no formato AA123456789AA.")
        log(f"  {aviso}")
        if cfg.responder_no_grupo:
            tg.responder(chat["id"], msg["message_id"], f"⚠️ {aviso}")
        return

    if adb is None:  # modo --so-ler: mostra os códigos sem os inserir na app
        log(f"  Lido(s): {', '.join(codigos)}")
        tg.responder(chat["id"], msg["message_id"], "🔎 Teste de leitura (não inserido):\n" + "\n".join(codigos))
        return

    inseridos_agora, repetidos, falhados, em_espera = [], [], [], []
    for codigo in codigos:
        if cfg.ignorar_repetidos and codigo in inseridos:
            log(f"  {codigo}: já tinha sido inserido, ignorado")
            repetidos.append(codigo)
            continue
        if pendentes is not None and any(p["codigo"] == codigo for p in pendentes):
            em_espera.append(f"{codigo}: já está em espera")
            continue
        try:
            mensagem, morada = inserir_na_app(adb, cfg, codigo, tg, chat["id"])
        except Exception as e:
            motivo = motivo_de_espera(str(e), cfg)
            if motivo and pendentes is not None:
                log(f"  {codigo}: fica em espera ({e})")
                pendentes.append({
                    "codigo": codigo, "chat_id": chat["id"], "message_id": msg["message_id"],
                    "grupo": grupo, "remetente": remetente,
                    "inicio": time.time(), "proxima": time.time() + INTERVALO_PENDENTES,
                })
                em_espera.append(f"{codigo}: {motivo[1]}")
                continue
            log(f"  {codigo}: ERRO ao inserir na app: {e}")
            registar(codigo, "erro", grupo, remetente)
            falhados.append(f"{codigo} ({e})")
            continue
        log(f"  {codigo}: inserido na app" + (f" ({mensagem})" if mensagem else "")
            + (f" — {morada}" if morada else ""))
        registar(codigo, "inserido", grupo, remetente)
        inseridos.add(codigo)
        inseridos_agora.append(texto_inserido(codigo, mensagem, morada))

    if cfg.responder_no_grupo:
        linhas = (inseridos_agora
                  + [f"↩️ Já inserido antes: {c}" for c in repetidos]
                  + [f"⏳ {c}" for c in em_espera]
                  + [f"❌ Erro ao inserir: {c}" for c in falhados])
        tg.responder(chat["id"], msg["message_id"], "\n".join(linhas))


def executar(cfg, adb):
    tg = Telegram(cfg.token)
    bot = tg.chamar("getMe")
    log(f"Ligado ao Telegram como @{bot['username']}")
    if not bot.get("can_read_all_group_messages"):
        log("Aviso: o privacy mode do bot está ligado; ele só vê fotos no grupo se for administrador.")
    log("À espera de fotos… (Ctrl+C para parar)")

    tg.offset = carregar_offset()
    inseridos = carregar_inseridos()
    pendentes = []  # códigos à espera de serem atribuídos à rota
    while True:
        if pendentes and adb is not None:
            try:
                tentar_pendentes(tg, adb, cfg, inseridos, pendentes)
            except Exception as e:
                log(f"Erro ao repetir códigos em espera: {e}")
        if not tg.fila:
            try:
                tg.fila.extend(tg.receber())
            except RuntimeError as e:
                log(f"Erro no Telegram: {e}. Nova tentativa em 5 s…")
                time.sleep(5)
            continue

        upd = tg.fila.popleft()
        msg = upd.get("message") or upd.get("channel_post")
        if msg and COMANDO_LIMPAR.match(msg.get("text") or "") and (
                cfg.grupo_id is None or msg["chat"]["id"] == cfg.grupo_id):
            copia = limpar_historico()
            inseridos.clear()
            log(f"Histórico limpo por {nome_remetente(msg)}" + (f" (cópia em {copia})" if copia else ""))
            tg.responder(msg["chat"]["id"], msg["message_id"],
                         "🧹 Histórico de códigos limpo. Os códigos já inseridos podem voltar a ser inseridos."
                         + (f"\n(Cópia guardada no PC: historico_antigo/{copia.name})" if copia else ""))
        elif msg:
            try:
                processar_mensagem(msg, tg, adb, cfg, inseridos, pendentes)
            except Exception as e:
                log(f"Erro ao processar mensagem: {e}")
        elif "callback_query" in upd:  # botão de uma pergunta que já expirou
            try:
                tg.chamar("answerCallbackQuery", {"callback_query_id": upd["callback_query"]["id"],
                                                  "text": "Esta pergunta já não está ativa."})
            except Exception:
                pass
        guardar_offset(upd["update_id"] + 1)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    p = argparse.ArgumentParser(description="Passa códigos de registo do Telegram para uma app Android.")
    p.add_argument("--config", default=str(BASE / "config.ini"))
    p.add_argument("--testar-codigo", metavar="CODIGO", help="escreve só este código na app e termina")
    p.add_argument("--testar-imagem", metavar="FICHEIRO", help="mostra os códigos lidos de uma imagem e termina")
    p.add_argument("--so-ler", action="store_true",
                   help="recebe as fotos do grupo e responde com os códigos lidos, sem usar a app/ADB")
    p.add_argument("--guardar-login", action="store_true",
                   help="guarda o utilizador e a password da MobiCTT no Gestor de Credenciais do Windows")
    p.add_argument("--apagar-login", action="store_true", help="apaga as credenciais guardadas")
    p.add_argument("--testar-login", action="store_true",
                   help="se a app estiver no ecrã de login, inicia sessão e termina")
    p.add_argument("--historico", metavar="FICHEIRO", help="usar outro ficheiro de histórico (para testes)")
    p.add_argument("--limpar-historico", action="store_true",
                   help="começa um histórico novo (o atual fica guardado em historico_antigo/)")
    args = p.parse_args()

    if args.historico:
        global FICHEIRO_HISTORICO
        FICHEIRO_HISTORICO = Path(args.historico)

    if args.limpar_historico:
        copia = limpar_historico()
        print(f"Histórico limpo. Cópia guardada em: {copia}" if copia else "Não havia histórico para limpar.")
        print("Se o programa estiver a correr, reinicia-o (ou usa /limpar_historico no grupo).")
        return
    if args.guardar_login:
        guardar_login()
        return
    if args.apagar_login:
        apagar_login()
        return

    if args.testar_imagem:
        codigos, total = ler_codigos(Path(args.testar_imagem).read_bytes())
        print(f"Códigos lidos: {total}. No formato AA123456789AA: {codigos or 'nenhum'}")
        return

    cfg = Config(Path(args.config))
    if args.so_ler:
        if not cfg.token:
            sys.exit("Falta o token do bot em config.ini.")
        log("Modo de teste: só leitura, nada é inserido na app.")
        try:
            executar(cfg, None)
        except KeyboardInterrupt:
            log("Parado.")
        return

    adb = Adb(cfg.adb, cfg.dispositivo)
    adb.verificar()

    if args.testar_login:
        try:
            tg = Telegram(cfg.token) if cfg.token else None
            if tg:
                tg.offset = carregar_offset()
            ecra = garantir_sessao(adb, cfg, tg, cfg.grupo_id)
        except RuntimeError as e:
            sys.exit(f"Erro: {e}")
        log("Ecrã atual — elementos: " + ", ".join(sorted(ecra)))
        return

    if args.testar_codigo:
        codigo = args.testar_codigo.strip().upper()
        if not FORMATO_CODIGO.match(codigo):
            sys.exit(f"{codigo} não está no formato AA123456789AA.")
        try:
            mensagem, morada = inserir_na_app(adb, cfg, codigo)
        except RuntimeError as e:
            sys.exit(f"Erro: {e}")
        log(texto_inserido(codigo, mensagem, morada))
        return

    if not cfg.token:
        sys.exit("Falta o token do bot em config.ini.")
    try:
        executar(cfg, adb)
    except KeyboardInterrupt:
        log("Parado.")


if __name__ == "__main__":
    main()
