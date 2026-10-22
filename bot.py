import os
import time
import sqlite3
import logging
from datetime import datetime, timezone
import requests
import threading
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
DB_PATH = os.getenv("DB_PATH", "historico.db")
POLL_SECONDS = int(os.getenv("TELEGRAM_POLL_SECONDS", "3"))
CTRADER_CLIENT_ID = os.getenv("CTRADER_CLIENT_ID", "").strip()
CTRADER_CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET", "").strip()
CTRADER_ENV = os.getenv("CTRADER_ENV", "demo").strip().lower()
session = requests.Session()
offset = 0
paused = False

HELP = """🤖 Bot IA Day Trade — cTrader Demo
/start — iniciar e ver ajuda
/ajuda — comandos
/status — estado da configuração
/historico — últimos eventos
/pausar — pausar alertas
/retomar — retomar alertas

Modo SOMENTE SINAIS: nenhuma ordem é enviada.
A integração com o mercado cTrader ainda depende do registro do app Open API e da autorização OAuth.
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
    with sqlite3.connect(DB_PATH) as con:
        con.execute("INSERT INTO events(ts,event_type,details) VALUES(?,?,?)",
                    (datetime.now(timezone.utc).isoformat(), kind, details))

def tg(method, payload=None):
    if not TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN não configurado.")
        return None
    try:
        response = session.post(f"https://api.telegram.org/bot{TOKEN}/{method}",
                                json=payload or {}, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logging.warning("Erro Telegram %s: %s", method, exc)
        return None

def status_text():
    telegram_ready = bool(TOKEN and CHAT_ID)
    ctrader_ready = bool(CTRADER_CLIENT_ID and CTRADER_CLIENT_SECRET)
    return (
        "Estado: ativo para comandos Telegram\n"
        f"Telegram configurado: {'sim' if telegram_ready else 'não'}\n"
        f"Credenciais app cTrader configuradas: {'sim' if ctrader_ready else 'não'}\n"
        f"Ambiente selecionado: {CTRADER_ENV}\n"
        "Cotações cTrader: ainda não conectadas\n"
        "Envio de ordens: DESATIVADO"
    )

def history_text():
    with sqlite3.connect(DB_PATH) as con:
        rows = con.execute("SELECT ts,event_type,details FROM events ORDER BY id DESC LIMIT 10").fetchall()
    if not rows:
        return "Ainda não há eventos registrados."
    return "📚 HISTÓRICO\n" + "\n".join(
        f"{ts[:16]} | {kind}: {details}" for ts, kind, details in rows
    )

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
        command = raw.split()[0].lower() if raw else ""
        if command in ("/start", "/ajuda"):
            record("comando", command)
            tg("sendMessage", {"chat_id": chat_id, "text": HELP})
        elif command == "/status":
            tg("sendMessage", {"chat_id": chat_id, "text": status_text()})
        elif command == "/historico":
            tg("sendMessage", {"chat_id": chat_id, "text": history_text()})
        elif command == "/pausar":
            paused = True
            record("controle", "alertas pausados")
            tg("sendMessage", {"chat_id": chat_id, "text": "Alertas pausados. Ordens seguem desativadas."})
        elif command == "/retomar":
            paused = False
            record("controle", "alertas retomados")
            tg("sendMessage", {"chat_id": chat_id, "text": "Bot retomado. A integração de mercado ainda está pendente."})
        else:
            tg("sendMessage", {"chat_id": chat_id, "text": "Comando não reconhecido. Envie /ajuda."})

app = FastAPI(title="Bot IA Day Trade Telegram", description="Somente sinais; nenhuma ordem é enviada.")

@app.get("/")
def health():
    return {"status": "ok", "modo": "somente_sinais", "ordens_ativas": False,
            "telegram_configurado": bool(TOKEN and CHAT_ID),
            "ctrader_conectado": False,
            "mensagem": "API do bot online. Integração cTrader ainda precisa ser autorizada."}

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
