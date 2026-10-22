# Bot IA Day Trade Telegram — cTrader Demo

Projeto em português, modo SOMENTE SINAIS. Não envia ordens de compra ou venda.

## Estado
O bot Telegram responde a /start, /ajuda, /status e /historico. O adaptador de mercado cTrader ainda precisa de registro do app Open API e autorização OAuth antes de produzir sinais reais de mercado. Sem essas credenciais, o bot informa que a integração está pendente e não inventa preços.

## Configuração
Variáveis de ambiente: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `CTRADER_CLIENT_ID`, `CTRADER_CLIENT_SECRET`, `CTRADER_ENV=demo`.

Nunca publique tokens, senhas ou client secrets no GitHub. Configure segredos na hospedagem.

## Teste Android/Termux
```bash
pkg update
pkg install python
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN='TOKEN_DO_BOT'
export TELEGRAM_CHAT_ID='SEU_ID_NUMERICO'
python bot.py
```
Envie `/start` ao bot no Telegram.

## Hospedagem
Configure um Background Worker contínuo usando `render.yaml`. Escolha um plano que não suspenda o processo e configure os segredos no painel. Para histórico persistente em produção, use disco persistente ou PostgreSQL.

## Segurança
O código não tem rotina de envio de ordens. Teste em demo. Sinais técnicos não garantem lucro. A alavancagem aumenta o risco.