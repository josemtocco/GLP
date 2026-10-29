# Guia: self-hosted runner no Brasil (para o Globoplay)

O Globoplay bloqueia por regiao. O runner padrao do GitHub roda nos EUA e
recebe **HTTP 403** (`Regiao detectada pelo IP: US`). Para gerar a lista
completa e automatica, voce precisa de um runner com **IP do Brasil**.

Um **PC residencial no Brasil** (o seu, ou um que fique ligado) e mais
confiavel que uma VPS brasileira de datacenter — muitos servicos tambem
bloqueiam faixas de datacenter.

## 1. Pre-requisitos na maquina (Brasil)

- Conexao de internet residencial brasileira (sem VPN).
- **Python 3.11+** instalado e no PATH.
  - Windows: baixe do <https://python.org> e marque "Add python.exe to PATH".
- **git** instalado.
- Teste a regiao do IP:
  ```bash
  curl https://ipinfo.io/country
  ```
  Deve retornar `BR`.

## 2. Registrar o runner no repositorio

1. No GitHub, va em **Settings -> Actions -> Runners -> New self-hosted runner**.
2. Escolha o sistema (Linux / Windows) e siga os comandos mostrados na tela
   (download, `config`, `run`). Durante o `config`, quando pedir **labels**,
   adicione a label `br-runner` (o workflow procura por ela).
3. Deixe o runner rodando. Para que ele fique sempre ativo, instale como servico:
   - Linux: `sudo ./svc.sh install` e `sudo ./svc.sh start`
   - Windows: o instalador oferece rodar como servico do Windows.

> O workflow ja esta com:
> ```yaml
> runs-on: [self-hosted, br-runner]
> ```

## 3. Seguranca (importante)

Como voce guarda credenciais da Globo nos Secrets e o runner roda na sua
maquina, use **sempre um repositorio PRIVADO**. Em repositorio publico,
terceiros poderiam abrir pull requests que executam codigo no seu runner.

## 4. Secrets necessarios

Em **Settings -> Secrets and variables -> Actions**:

- `GLOBO_EMAIL` e `GLOBO_PASSWORD` (login da conta Globo), **ou**
- `GLBID` (cookie de sessao). Para pegar o `GLBID`:
  1. Entre no globoplay.globo.com logado.
  2. F12 -> **Application** -> **Cookies** -> `globo.com`.
  3. Copie o valor do cookie `GLBID`.

## 5. Primeira execucao

Em **Actions -> Atualizar playlist M3U (Globoplay) -> Run workflow**.
Confira o log: deve aparecer `Regiao detectada pelo IP: BR`.
Depois ele roda sozinho a cada 6 horas.

## 6. Alternativa sem GitHub Actions (cron direto no PC)

Se preferir nao usar runner, agende o script direto na sua maquina:

- **Linux (crontab)** — a cada 6 horas:
  ```cron
  0 */6 * * * cd /caminho/do/projeto && GLOBO_EMAIL=... GLOBO_PASSWORD=... python gerar_globoplay.py && git add -A && git commit -m auto && git push
  ```
- **Windows (Agendador de Tarefas):** crie uma tarefa que roda
  `rodar_no_brasil.bat` a cada 6 horas e depois faz `git push`.

## 7. Problemas comuns

| Sintoma | Causa provavel | Solucao |
|---------|----------------|---------|
| `Regiao detectada pelo IP: US` / HTTP 403 | runner nao esta no Brasil | use o self-hosted runner BR / gere no seu PC |
| Lista vazia mesmo no BR | sem login valido | confira `GLOBO_EMAIL`/`GLOBO_PASSWORD` ou `GLBID` |
| Canal marcado `(DRM)` nao toca | Widevine nao roda em SS IPTV/VLC | use `--no-drm` para excluir |
| Lista nao atualiza no SS IPTV | cache do app | remova e adicione a playlist de novo |
| `push ... (fetch first)` | remoto a frente | o workflow ja faz `git pull --rebase` antes do push |
