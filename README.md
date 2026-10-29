# Lista M3U do Globoplay (TV Globo ao vivo) para o SS IPTV

Projeto completo e pronto para implantar no GitHub. Ele gera um arquivo
`playlist.m3u` com os canais ao vivo do Globoplay, otimizado para o **SS IPTV**,
e se atualiza sozinho a cada 6 horas.

Fonte: <https://globoplay.globo.com/tv-globo/ao-vivo/6120663/>

## O que o projeto faz

- Descobre os canais ao vivo do Globoplay (partindo do canal TV Globo, id `6120663`).
- Resolve o stream HLS de cada canal e verifica se esta no ar.
- Gera `playlist.m3u` com:
  - o **nome** de cada canal;
  - os canais **separados por categoria** (`group-title`), como aparecem no site;
  - atributos pensados para o SS IPTV (`tvg-id`, `tvg-name`, `tvg-logo`, `group-title`).
- **Atualiza a cada 6 horas** pelo GitHub Actions.
- Regra de reconciliacao a cada atualizacao:
  - **mantem** os canais que estao ativos;
  - **remove** um canal somente depois de **6 atualizacoes seguidas** com ele fora do ar;
  - **acrescenta** automaticamente os canais novos encontrados.
- O contador de falhas de cada canal fica salvo em `estado_canais.json`.

Todos os arquivos ficam na **raiz do repositorio** (o workflow do GitHub Actions
fica em `.github/workflows/`, como exige o GitHub).

## Importante sobre o Globoplay (leia antes)

O Globoplay **nao e aberto**. Para gerar a lista com os streams funcionando:

1. **Login/assinatura** — os canais ao vivo exigem uma conta Globo (e assinatura
   para os canais pagos). Informe as credenciais (veja abaixo).
2. **IP do Brasil** — o Globoplay bloqueia por regiao. O runner padrao do GitHub
   roda nos EUA e costuma receber **HTTP 403**. Para a lista completa, use um
   **self-hosted runner no Brasil** (passo a passo em `GUIA-RUNNER-BRASIL.md`).
3. **DRM (Widevine)** — varios canais da Globo usam DRM, que **nao toca** no
   SS IPTV nem no VLC. Esses canais sao marcados com `(DRM)` no nome. Use
   `--no-drm` (ou `INCLUDE_DRM=0`) para exclui-los da lista.

## Como implantar no GitHub

1. Crie um repositorio **privado** (recomendado, porque voce vai guardar credenciais).
2. Envie todos os arquivos deste projeto para a raiz do repositorio.
3. Em **Settings -> Secrets and variables -> Actions**, crie os segredos:
   - `GLOBO_EMAIL` e `GLOBO_PASSWORD` (login da sua conta Globo), **ou**
   - `GLBID` (cookie de sessao ja autenticado).
4. Configure um self-hosted runner no Brasil (veja `GUIA-RUNNER-BRASIL.md`).
5. Em **Actions**, abra o workflow "Atualizar playlist M3U (Globoplay)" e clique
   em **Run workflow** para a primeira execucao. Depois ele roda sozinho a cada 6h.

## Como usar no SS IPTV

1. Pegue o link **raw** do `playlist.m3u` do seu repositorio, por exemplo:
   `https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/playlist.m3u`
2. No SS IPTV: **Settings -> General -> Playlists -> Add -> External playlist**
   e cole o link acima.
3. Depois de cada atualizacao, se nao aparecer o conteudo novo, **remova e
   adicione a playlist de novo** para limpar o cache do app.

> Observacao: o tamanho dos botoes/blocos no SS IPTV e uma configuracao do
> proprio app (nao da sopara mudar pelo M3U). Os canais ja vao com `group-title`
> e `tvg-logo` para aparecerem organizados por categoria.

## Canais configurados (renovacao automatica por media_id)

O `config.json` ja vem com estes canais em `canais_fixos`. Cada um e resolvido
**pela media_id**, entao o gerador pede um link NOVO (token renovado) a cada
execucao de 6h - ou seja, **renovacao 100% automatica pelo GitHub** (rodando de
um IP do Brasil com login valido). Nao ha link que expira para voce trocar na mao.

| Canal | media_id | Categoria |
|-------|----------|-----------|
| TV Globo | 6120663 | TV Globo |
| GE TV | 11134179 | Esportes |
| Futura | 7420604 | Educacao |
| Malhacao Fast | 12136724 | Novelas |
| DPA Fast | 12136726 | Infantil |
| Receitas Fast | 11134191 | Gastronomia |

> Edite nome/categoria a vontade no `config.json`. Para adicionar outro canal,
> copie o numero da URL dele no Globoplay (`.../ao-vivo/`**`<media_id>`**`/`) e
> acrescente uma linha em `canais_fixos`.

> Observacao: como estes sao canais da Globo, varios resolvem via token de 6h
> e alguns podem exigir login/assinatura. O gerador renova o token sozinho a
> cada execucao. Se algum canal usar DRM (Widevine), ele vem marcado `(DRM)` e
> pode ser excluido com `--no-drm`.

### E se eu quiser colar um link /j/<token> na mao?

Da para usar a secao `canais_adicionais` do `config.json`, mas lembre: esse link
expira em **6 horas** e o GitHub nao consegue re-assinar. Por isso o caminho
recomendado e sempre o `media_id` acima (renovacao automatica).

## Rodar no seu PC (Brasil)

Como o catalogo completo so vem de um IP do Brasil, o jeito mais simples e gerar
a lista no seu proprio computador:

- **Windows:** abra `rodar_no_brasil.bat`, preencha as credenciais no topo do
  arquivo e de um duplo-clique.
- **Qualquer sistema:**
  ```bash
  export GLOBO_EMAIL="seu-email"
  export GLOBO_PASSWORD="sua-senha"
  python gerar_globoplay.py
  ```

Depois e so commitar o `playlist.m3u` e o `estado_canais.json` atualizados.

### Opcoes do gerador

| Opcao | Efeito |
|-------|--------|
| `--no-drm` | ignora canais com Widevine DRM (ou `INCLUDE_DRM=0`) |
| `--debug` | log detalhado (ou `GLOBO_DEBUG=1`) |

## Arquivos do projeto

| Arquivo | Para que serve |
|---------|----------------|
| `gerar_globoplay.py` | gerador principal (somente biblioteca padrao do Python) |
| `config.json` | canal-semente, lista de canais fixos e endpoints |
| `playlist.m3u` | **saida** — a lista para o SS IPTV |
| `estado_canais.json` | **saida** — estado/contador de falhas de cada canal |
| `rodar_no_brasil.bat` | gerar a lista no seu PC Windows |
| `.github/workflows/update.yml` | agendamento de 6 em 6 horas no GitHub Actions |
| `GUIA-RUNNER-BRASIL.md` | passo a passo do runner no Brasil |

## Requisitos

- Python 3.9+ (sem bibliotecas externas; so a biblioteca padrao).
- No Windows, instale o Python do <https://python.org> marcando
  **"Add python.exe to PATH"** (evita o atalho falso da Microsoft Store).

## Observacao legal

Use este projeto apenas com a **sua propria conta/assinatura** Globo e para uso
pessoal. Respeite os termos de uso do Globoplay.
