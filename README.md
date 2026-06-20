<h1 align="center">IRC Bot com Integração Telegram e Plugins</h1>
<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-3670A0?style=for-the-badge&logo=python&logoColor=ffdd54" />
  <img src="https://img.shields.io/badge/sqlite-%2307405e.svg?style=for-the-badge&logo=sqlite&logoColor=white" />
  <img src="https://img.shields.io/badge/Telegram-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white" />
  <img src="https://img.shields.io/badge/asyncio-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/status-active-success?style=for-the-badge" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=for-the-badge" />
</p>
<p align="center">
Bot IRC modular e assíncrono, com plugins extensíveis, integração Telegram
(notificações <strong>e</strong> controlo remoto), watchdog de ligação,
rate limiting e validação rigorosa de input.
</p>

---

### 🔧 Funcionalidades Principais

- Conexão segura via SSL/TLS a servidores IRC (com TCP keepalive)
- Entrada automática em canais definidos e autenticação via NickServ
- **Reconexão automática** com backoff e **heartbeat activo** (PING/PONG): força reconexão se o servidor deixar de responder
- Comandos administrativos com **autenticação por hostmask** (resistente a spoofing de nick)
- **Rate limiting** por `ident@host` (sobrevive a mudanças de nick)
- **Validação anti-CRLF** de nicks, canais e texto livre (previne injecção de comandos IRC)
- Plugins modulares (crypto, seen, admin, etc.)
- **Notificações Telegram** de eventos (join/part/quit, ping timeout, estado do bot)
- **Controlo remoto via Telegram** (`/status`, `/health`, `/reconnect`, `/restart`, `/quit`)
- Monitorização de outros bots no canal (alerta quando caem)
- Logging com rotação de ficheiros e níveis configuráveis

### 📁 Estrutura do Projeto

```
.
├── bot.py                      # Ponto de entrada e loop principal (asyncio)
├── config.py                   # Carrega e valida variáveis de ambiente (.env)
├── logger.py                   # Logging com rotação de ficheiros
├── requirements.txt            # Dependências Python
├── .env.example                # Template de configuração (copiar para .env)
├── .gitignore
├── LICENSE
└── plugins/
    ├── __init__.py
    ├── admin.py                # Autenticação de admin por hostmask
    ├── commands.py             # Despacho dos comandos IRC (!op, !kick, ...)
    ├── crypto.py               # Preços de cripto via API pública da Binance
    ├── http_clients.py         # Sessões aiohttp partilhadas
    ├── irc_validate.py         # Validação/sanitização de input IRC
    ├── seen.py                 # Persistência do !seen (SQLite)
    ├── telegram.py             # Notificações e helpers da Telegram Bot API
    ├── telegram_control.py     # Controlo remoto via long-polling
    └── misc.py                 # Reservado para utilitários futuros
```

### ✅ Requisitos

- **Python 3.10+** (usa `match`/`case` e *type unions* `X | None`)
- Acesso a um servidor IRC com SSL
- (Opcional) Bot Telegram + chat ID para notificações/controlo

### 🚀 Começar

1. Clonar o repositório

   ```bash
   git clone https://github.com/nunchuckcoder/ircbot.git
   cd bot_irc
   ```

2. Criar um ambiente virtual e instalar dependências

   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Criar e configurar o `.env`

   ```bash
   cp .env.example .env
   # editar .env com os teus valores reais
   ```

   Exemplo mínimo:

   ```env
   IRC_NICK=OMeuBot
   IRC_SERVER=irc.ptnet.org
   IRC_PORT=6697
   IRC_PASSWORD=senhaNickServ
   CANAIS=#portugal,#informática

   # ⚠️ Admins SÓ por hostmask (nunca por nick). Descobre a vhost com /whois <nick>
   IRC_ADMINS=OMeuNick!*@*.vhost.com

   # Telegram (opcional)
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=987654321
   CANAIS_COM_ALERTAS=#portugal
   ```

4. Executar o bot

   ```bash
   python bot.py
   ```

> ⚠️ **Importante:** `IRC_ADMINS` aceita **apenas hostmasks** (com `!`). O formato
> antigo só com nick (ex.: `admin1,admin2`) já não é suportado — o bot recusa-se a
> arrancar, porque qualquer pessoa podia mudar de nick e ganhar acesso de admin.

### 📌 Comandos IRC

| Comando                 | Descrição                                | Admin |
| ----------------------- | ---------------------------------------- | :---: |
| `!op [nick]`            | Dá op (em canal)                         |  ✅   |
| `!deop [nick]`          | Remove op (em canal)                     |  ✅   |
| `!voice <nick>`         | Dá voz (em canal)                        |  ✅   |
| `!devoice <nick>`       | Remove voz (em canal)                    |  ✅   |
| `!kick <nick> [motivo]` | Expulsa um utilizador (em canal)         |  ✅   |
| `!ban <nick> [motivo]`  | Bane e expulsa (em canal)                |  ✅   |
| `!kb <nick> [motivo]`   | Atalho para `!ban`                       |  ✅   |
| `!unban <nick>`         | Remove ban (em canal)                    |  ✅   |
| `!invite <nick>`        | Convida um utilizador (em canal)         |  ✅   |
| `!topic <texto>`        | Altera o tópico (em canal)               |  ✅   |
| `!join <#canal>`        | Bot entra num canal                      |  ✅   |
| `!part <#canal>`        | Bot sai de um canal                      |  ✅   |
| `!status [nick]`        | Estado real (próprio) ou consulta (admin)|   —   |
| `!seen <nick>`          | Última vez que o nick foi visto          |   —   |
| `!crypto <símbolo>`     | Preço de uma criptomoeda (EUR/USD)       |   —   |
| `!ajuda`                | Lista todos os comandos                  |   —   |

### 💬 Controlo remoto via Telegram

Disponível para os chat IDs em `TELEGRAM_ADMIN_CHAT_IDS`:

| Comando      | Descrição                                            |
| ------------ | ---------------------------------------------------- |
| `/status`    | Estado operacional resumido                          |
| `/health`    | Estado detalhado (pings, canais, última falha)       |
| `/channels`  | Canais configurados / activos / com alertas          |
| `/reconnect` | Força reconexão IRC imediata (mesmo processo)         |
| `/restart`   | Encerra com código de saída 75 para o supervisor relançar |
| `/quit`      | Encerra o bot de forma controlada                    |
| `/help`      | Mostra a ajuda                                       |

### 🛠️ Executar como serviço (systemd)

O `/restart` sai com **código 75** propositadamente, para que o gestor de serviços
relance o processo. Exemplo de unit (`/etc/systemd/system/ircbot.service`):

```ini
[Unit]
Description=IRC Bot com integração Telegram
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ircbot
WorkingDirectory=/opt/ircbot
ExecStart=/opt/ircbot/.venv/bin/python /opt/ircbot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ircbot.service
sudo journalctl -u ircbot -f
```

### 📈 Logs

Eventos importantes são gravados em `bot.log` (rotação: 5 ficheiros de 1 MB).
Os níveis ajustam-se via `LOG_LEVEL_FILE` e `LOG_LEVEL_CONSOLE` no `.env`.
INFO regista apenas nick + comando + canal; DEBUG inclui a hostmask completa
(para diagnóstico forense).

### 🔒 Segurança

- Autenticação de admins por **hostmask** (não por nick)
- **Validação anti-CRLF** em todo o input enviado ao servidor IRC
- **Rate limiting** por `ident@host`
- Tokens Telegram **redactados** nas mensagens de erro
- **Escape de HTML** em todos os dados do IRC antes de irem para o Telegram
- Sem credenciais no código — tudo via `.env` (que está no `.gitignore`)

### 🤝 Contribuição

Contribuições são bem-vindas! Abre um *issue* ou um *pull request*:

1. Faz fork do repositório
2. Cria uma branch (`git checkout -b minha-feature`)
3. Comita as alterações (`git commit -am 'Adiciona nova feature'`)
4. Faz push (`git push origin minha-feature`)
5. Abre um pull request

### 📜 Licença

Distribuído sob a licença **MIT**. Ver o ficheiro [`LICENSE`](LICENSE) para os detalhes.
