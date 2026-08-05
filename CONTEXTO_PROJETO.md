# Continuidade do projeto Cadu

Este documento foi preparado para que outra sessão do Codex consiga continuar o
trabalho em outro computador. Leia este arquivo antes de alterar o projeto.

## Objetivo

O projeto monitora notícias relacionadas a política, economia, negócios,
terceiro setor, empreendedorismo, cultura, esporte, ONGs, organizações sociais,
editais e temas de risco reputacional.

O sistema:

- coleta notícias de feeds RSS e Google Notícias;
- pode consultar Google Programmable Search quando a API estiver liberada;
- tem integração preparada para Instagram, ainda sem credenciais;
- classifica notícias por risco, tom e impacto;
- grava os resultados no MariaDB;
- gera relatório por e-mail;
- apresenta os dados em um dashboard Angular com API FastAPI/Python.

## Arquitetura

- `app/`: bot e API FastAPI em Python.
- `config/keywords.yaml`: palavras-chave e regras de classificação.
- `config/sources.yaml`: fontes e integrações habilitadas.
- `tests/`: testes automatizados do bot.
- `dashboard-web/`: frontend Angular servido por nginx.
- `docker-compose.yml`: ambiente local completo.
- MariaDB: banco de dados do sistema.

Serviços do Compose:

- `db`: MariaDB;
- `api`: FastAPI na porta `8000`;
- `worker`: agendamento das coletas e relatórios;
- `dashboard-web`: painel na porta `4200`.

## Estado do Git

Na última sincronização, a branch local `main` e `origin/main` estavam no commit:

```text
ca81a16 Melhoria bot email
```

Depois desse commit foram feitas alterações locais que podem ainda não estar
commitadas:

- inclusão das consultas temáticas na seção `google` de
  `config/sources.yaml`;
- proteção em `app/collectors.py` para que erros HTTP da Google Custom Search
  não interrompam toda a coleta nem imprimam a URL contendo a chave;
- criação deste documento.

Antes de trabalhar, executar:

```powershell
git status --short --branch
git diff
```

Não apagar alterações locais sem revisá-las.

## Resultado dos testes já realizados

A suíte Python passou após a migração completa do dashboard para FastAPI:

```text
38 passed
```

A coleta real realizada em 24/07/2026 retornou:

```json
{
  "encontrados": 658,
  "ultimas_72h": 658,
  "relevantes": 220,
  "descartados": 438,
  "novos": 220,
  "expirados_removidos": 0
}
```

Uma segunda coleta confirmou a deduplicação, retornando `novos: 0`.

Esses resultados vieram dos feeds RSS e do Google Notícias. O Instagram não
participou da coleta.

## Google

Há duas integrações diferentes:

1. `google_news`: busca temática gratuita pelo RSS do Google Notícias. Está
   habilitada e funcionou.
2. `google`: Google Programmable Search / Custom Search JSON API. Está
   desabilitada em `config/sources.yaml`.

A tentativa com a chave anterior respondeu:

```text
403 PERMISSION_DENIED
This project does not have the access to Custom Search JSON API.
```

No PC de casa:

1. Revogar a chave anterior, pois ela apareceu em um traceback durante o teste.
2. Criar uma chave nova.
3. Habilitar a Custom Search JSON API no mesmo projeto do Google Cloud.
4. Confirmar que o Programmable Search Engine e o `GOOGLE_CSE_ID` estão
   corretos.
5. Atualizar `GOOGLE_API_KEY` e `GOOGLE_CSE_ID` no `.env`.
6. Alterar `google.enabled` para `true` em `config/sources.yaml`.
7. Recriar `api` e `worker` e executar uma coleta.

Nunca registrar ou imprimir a URL completa de erro da API, pois ela contém a
chave no parâmetro `key`.

## Instagram

A integração está preparada, porém desabilitada:

```yaml
instagram:
  enabled: false
```

As variáveis ainda não configuradas são:

- `INSTAGRAM_ACCESS_TOKEN`;
- `INSTAGRAM_USER_ID`.

Não habilitar o Instagram até existirem credenciais válidas da Meta para uma
conta profissional.

## E-mail

O relatório é enviado pelo endpoint:

```text
POST http://localhost:8000/relatorios/enviar
```

O `.env` possui configuração SMTP e dois destinatários em `REPORT_TO`. Não
copiar os valores secretos para este documento, commits, logs ou conversas.

Na rede da empresa, o envio falhou antes da autenticação:

```text
ConnectionRefusedError / Timeout
```

Foram testadas as portas do Brevo `587`, `2525` e `465`. Todas expiraram tanto
no Docker quanto diretamente no Windows. A hipótese principal é bloqueio da
rede corporativa.

No PC de casa:

1. Testar conectividade com `smtp-relay.brevo.com` nas portas `587` e `2525`.
2. Subir os serviços com o `.env` local.
3. Executar primeiro uma coleta.
4. Confirmar explicitamente os destinatários antes de enviar.
5. Chamar `/relatorios/enviar` e conferir a resposta.

Resposta esperada:

```json
{
  "enviado": true,
  "destinatarios": 2
}
```

Se SMTP continuar bloqueado, considerar a API HTTP do Brevo pela porta `443`.
Isso requer uma chave de API própria; não assumir que a senha SMTP funciona
como chave HTTP.

## Dashboard

O dashboard estava disponível localmente em:

```text
http://localhost:4200
```

Ele usa autenticação HTTP Basic configurada por:

- `DASHBOARD_USER`;
- `DASHBOARD_PASSWORD`.

No último teste essas duas linhas não estavam mais presentes no `.env`, fazendo
o contêiner `dashboard-web` reiniciar com a mensagem:

```text
DASHBOARD_PASSWORD não configurada
```

Adicionar novamente as variáveis ao `.env` antes de subir o painel. Não colocar
os valores neste documento nem no Git.

O antigo link público temporário do Pinggy expirou e não deve ser reutilizado.

## Preparação no PC de casa

Clonar ou atualizar o repositório:

```powershell
git clone https://github.com/LcTheRunner/Projeto_bot.git
cd Projeto_bot
git pull --ff-only origin main
```

Se este documento e as correções locais ainda não estiverem no Git, copiar a
pasta atual ou criar um commit seguro antes de mudar de computador. O `.env`
deve ser transferido separadamente e nunca enviado ao GitHub.

Criar o `.env` a partir do exemplo e preencher os segredos:

```powershell
Copy-Item .env.example .env
```

Subir o ambiente:

```powershell
docker compose up -d --build
docker compose ps
```

Verificar a API:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Executar os testes. A imagem de produção não inclui `pytest`, portanto uma forma
temporária é:

```powershell
docker compose exec api pip install pytest
docker compose exec -e PYTHONPATH=/app api pytest -q
```

Executar a coleta:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/coletas `
  -TimeoutSec 300
```

Consultar estatísticas:

```powershell
Invoke-RestMethod http://localhost:8000/estatisticas/72h
```

Enviar o relatório somente após confirmar os destinatários:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://localhost:8000/relatorios/enviar `
  -TimeoutSec 120
```

## Cuidados importantes

- Não commitar `.env`.
- Não mostrar chaves, tokens ou senhas em logs.
- Revogar a chave do Google que apareceu no traceback.
- Preservar as alterações locais ao atualizar o Git.
- Confirmar destinatários antes de enviar relatórios.
- Manter o Instagram desligado enquanto não houver credenciais.
- Se uma integração externa falhar, a coleta das demais fontes deve continuar.

## Próximas tarefas recomendadas

1. Testar o SMTP fora da rede corporativa.
2. Habilitar corretamente a Custom Search JSON API e testar a chave nova.
3. Restaurar as variáveis de autenticação do dashboard no `.env`.
4. Rodar os 14 testes novamente.
5. Confirmar visualmente o relatório recebido.
6. Criar testes para a nova tolerância a erros da Google Custom Search.
7. Revisar e commitar apenas arquivos seguros, mantendo `.env` ignorado.
