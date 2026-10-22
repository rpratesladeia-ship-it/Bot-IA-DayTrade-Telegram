import os
import time
import sqlite3
import logging
import secrets
from datetime import datetime, timezone
from urllib.parse import urlencode
import threading

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DB_PATH = os.getenv("DB_PATH", "historico.db")
POLL_SECONDS = max(2, int(os.getenv("TELEGRAM_POLL_SECONDS", "3")))
CTRADER_CLIENT_ID = os.getenv("CTRADER_CLIENT_ID", "").strip()
CTRADER_CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET", "").strip()
CTRADER_ENV = os.getenv("CTRADER_ENV", "demo").strip().lower()
CTRADER_REDIRECT_URI = os.getenv("CTRADER_REDIRECT_URI", "").strip()
CTRADER_TARGET_ACCOUNT_ID = os.getenv("CTRADER_TARGET_ACCOUNT_ID", "").strip()
session = requests.Session()
offset = 0
paused = False
oauth_states = {}
oauth_token = None
oauth_token_expiry = 0

HELP = """🤖 Bot IA Day Trade — cTrader
/start — ajuda
/ajuda — comandos
/status — estado do serviço
/conectar — iniciar autorização cTrader
/historico — últimos eventos
/pausar — pausar alertas
/retomar — retomar alertas

Modo SOMENTE SINAIS: este serviço não envia ordens.
A autorização OAuth não significa que as cotações já estejam conectadas.
"""

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            details TEXT NOT NULL
        )""")

def record(kind, details):
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT INTO events(ts,event_type,details) VALUES(?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), kind, details))

def tg(method, payload=None):
    if not TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN não configurado.")
        return None
    try:
        response = session.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                json=payload or {}, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logging.warning("Erro Telegram %s: %s", method, type(exc).__name__)
        return None

def oauth_valid():
    return bool(oauth_token and time.time() < oauth_token_expiry)

def status_text():
    return (
        "Estado: ativo para comandos Telegram\n"
        f"Telegram configurado: {'sim' if TOKEN and CHAT_ID else 'não'}\n"
        f"App cTrader configurado: {'sim' if CTRADER_CLIENT_ID and CTRADER_CLIENT_SECRET and CTRADER_REDIRECT_URI else 'não'}\n"
        f"Ambiente: {CTRADER_ENV}\n"
        f"OAuth autorizado nesta instância: {'sim' if oauth_valid() else 'não'}\n"
        f"Conta-alvo configurada: {'terminada em ' + CTRADER_TARGET_ACCOUNT_ID[-4:] if CTRADER_TARGET_ACCOUNT_ID else 'não'}\n"
        "Cotações cTrader: NÃO conectadas\n"
        "Envio de ordens: DESATIVADO"
    )

def history_text():
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("SELECT ts,event_type,details FROM events ORDER BY id DESC LIMIT 10").fetchall()
    return "📚 HISTÓRICO\n" + ("\n".join(f"{ts[:16]} | {kind}: {details}" for ts, kind, details in rows)
                                  if rows else "Ainda não há eventos registrados.")

def connect_message():
    return "Abra o endereço do serviço e acesse /ctrader/connect para iniciar a autorização. Use /status depois para conferir."

def handle_updates():
    global offset, paused
    data = tg("getUpdates", {"offset": offset + 1, "timeout": 5, "allowed_updates": ["message"]})
    if not data or not data.get("ok"):
        return
    for update in data.get("result", []):
        offset = max(offset, update["update_id"])
        message = update.get("message", {})
        chat_id = str(message.get("chat", {}).get("id", ""))
        if not chat_id or (CHAT_ID and chat_id != CHAT_ID):
            continue
        raw = (message.get("text") or "").strip()
        command = raw.split()[0].lower().split("@")[0] if raw else ""
        if command in ("/start", "/ajuda"):
            record("comando", command)
            tg("sendMessage", {"chat_id": chat_id, "text": HELP})
        elif command == "/status":
            tg("sendMessage", {"chat_id": chat_id, "text": status_text()})
        elif command == "/conectar":
            if not (CTRADER_CLIENT_ID and CTRADER_CLIENT_SECRET and CTRADER_REDIRECT_URI):
                tg("sendMessage", {"chat_id": chat_id, "text": "Configuração pendente no Render: CTRADER_CLIENT_ID, CTRADER_CLIENT_SECRET e CTRADER_REDIRECT_URI. Não envie segredos pelo Telegram."})
            else:
                tg("sendMessage", {"chat_id": chat_id, "text": connect_message()})
        elif command == "/historico":
            tg("sendMessage", {"chat_id": chat_id, "text": history_text()})
        elif command == "/pausar":
            paused = True
            record("controle", "alertas pausados")
            tg("sendMessage", {"chat_id": chat_id, "text": "Alertas pausados. Ordens desativadas."})
        elif command == "/retomar":
            paused = False
            record("controle", "alertas retomados")
            tg("sendMessage", {"chat_id": chat_id, "text": "Bot retomado. Cotações ainda não conectadas; ordens desativadas."})
        else:
            tg("sendMessage", {"chat_id": chat_id, "text": "Comando não reconhecido. Envie /ajuda."})

app = FastAPI(title="Bot IA Day Trade Telegram", description="Somente sinais; nenhuma ordem é enviada.")

@app.get("/")
def health():
    return {"status": "ok", "modo": "somente_sinais", "ordens_ativas": False,
            "telegram_configurado": bool(TOKEN and CHAT_ID),
            "ctrader_oauth_autorizado": oauth_valid(),
            "ctrader_conectado": False,
            "mensagem": "Serviço online; autorização e feed de cotações são etapas separadas."}

@app.get("/status")
def http_status():
    return {"status": status_text(), "ordens_ativas": False}

@app.get("/ctrader/connect")
def ctrader_connect():
    if CTRADER_ENV != "demo":
        raise HTTPException(status_code=403, detail="Este serviço foi configurado para aceitar apenas ambiente demo.")
    if not (CTRADER_CLIENT_ID and CTRADER_CLIENT_SECRET and CTRADER_REDIRECT_URI):
        raise HTTPException(status_code=503, detail="Configure o app cTrader e o callback nas variáveis do Render.")
    state = secrets.token_urlsafe(32)
    oauth_states[state] = time.time()
    params = {
        "client_id": CTRADER_CLIENT_ID,
        "redirect_uri": CTRADER_REDIRECT_URI,
        "scope": "trading",
        "product": " cTrader",
        "state": state,
    }
    return RedirectResponse("https://id.ctrader.com/my/settings/openapi/grantingaccess/?" + urlencode(params), status_code=302)

@app.get("/ctrader/callback")
def ctrader_callback(code: str = "", state: str = "", error: str = ""):
    global oauth_token, oauth_token_expiry
    issued = oauth_states.pop(state, None) if state else None
    if error:
        record("ctrader_oauth", "autorização recusada")
        return HTMLResponse("<h3>Autorização não concluída.</h3><p>Volte ao Telegram e consulte /status.</p>", status_code=400)
    if not issued or time.time() - issued > 600 or not code:
        raise HTTPException(status_code=400, detail="Estado OAuth inválido/expirado ou código ausente. Reinicie o fluxo.")
    try:
        response = requests.post("https://openapi.ctrader.com/apps/token", data={
            "grantType": "authorization_code",
            "code": code,
            "redirect_uri": CTRADER_REDIRECT_URI,
            "client_id": CTRADER_CLIENT_ID,
            "client_secret": CTRADER_CLIENT_SECRET,
        }, timeout=20)
        response.raise_for_status()
        payload = response.json()
        access = payload.get("accessToken") or payload.get("access_token")
        expires = int(payload.get("expiresIn") or payload.get("expires_in") or 0)
        if not access or expires <= 0:
            raise ValueError("Resposta OAuth sem token ou validade.")
        oauth_token = access
        oauth_token_expiry = time.time() + expires
        record("ctrader_oauth", "token recebido em memória; feed ainda não conectado")
        return HTMLResponse("<h3>Autorização concluída.</h3><p>O token está somente na memória desta instância. A conta autorizada ainda precisa ser validada e o feed de cotações implementado. Nenhuma ordem será enviada.</p>")
    except Exception as exc:
        logging.warning("Falha na troca OAuth cTrader: %s", type(exc).__name__)
        record("ctrader_oauth", "falha na troca do código OAuth")
        raise HTTPException(status_code=502, detail="Falha na autorização OAuth. Consulte os logs sem compartilhar segredos.")

def polling_loop():
    init_db()
    logging.info("Bot iniciado em modo somente sinais; ordens desativadas.")
    if TOKEN and CHAT_ID:
        tg("sendMessage", {"chat_id": CHAT_ID, "text": "🤖 Bot iniciado. Modo SOMENTE SINAIS. Use /start ou /status."})
    while True:
        try:
            handle_updates()
            time.sleep(POLL_SECONDS)
        except Exception:
            logging.exception("Erro no loop Telegram")
            time.sleep(5)

@app.on_event("startup")
def startup():
    threading.Thread(target=polling_loop, daemon=True).start()

if __name__ == "__main__":
    uvicorn.run("bot:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
