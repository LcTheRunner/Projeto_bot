# Monitor de Impacto Midiático

MVP em Python para coletar notícias, encontrar temas monitorados, classificar risco/tom/impacto e produzir estatísticas semanais por veículo, editoria e jornalista. O banco de produção é MariaDB; SQLite é usado automaticamente fora do Docker para facilitar testes.

## Executar com Docker

1. Copie `.env.example` para `.env`.
2. Preencha `GOOGLE_API_KEY` e `GOOGLE_CSE_ID` para habilitar Google Programmable Search.
3. Execute `docker compose up --build`.
4. Abra `http://localhost:8000/docs`.
5. Abra o painel gerencial em `http://localhost:4200`.
6. Inicie uma coleta em `POST /coletas` ou aguarde a rotina diária das 04h30.

O relatório sai às 07h00 quando SMTP estiver preenchido. Também pode ser disparado por `POST /relatorios/enviar`. Para Instagram, informe conta profissional/token Meta e ative `instagram.enabled` em `config/sources.yaml`.

Consultas principais: `GET /noticias?risco=10` e `GET /estatisticas/semana?termo=corrupção com O.S.`.

## Painel gerencial

O frontend Angular fica em `dashboard-web` e consulta a API analítica Java/Spring Boot em `dashboard-api`. O painel mostra KPIs, evolução temporal, distribuição de risco e tom, menções por palavra-chave, veículos e detalhes das notícias. Os filtros consultam o MariaDB em tempo real.

O primeiro administrador é criado a partir de `DASHBOARD_USER` e
`DASHBOARD_PASSWORD`. Novos usuários podem se cadastrar na tela de login com
usuário, e-mail e senha; administradores também podem criar contas pelo
painel. Cada usuário possui uma lista independente de
palavras-chave. O coletor pesquisa a união dos termos ativos, enquanto a API
analítica entrega a cada conta apenas as notícias que correspondem à sua lista.
As 17 palavras-chave oficiais são entregues por padrão a todas as contas, mas
cada usuário pode removê-las. A tela aceita inclusão e remoção em lote, elimina
duplicatas e reconhece vírgula, ponto, ponto e vírgula, dois-pontos, aspas e
quebras de linha como separadores.

O dashboard abre em **Brasil inteiro**. O seletor de abrangência no cabeçalho
tem busca textual e permite selecionar todo o Estado do Rio de Janeiro ou
combinar livremente vários dos 92 municípios fluminenses, incluindo
**Rio de Janeiro (capital)**, sem alterar a coleta nacional.

No cadastro, um código numérico de uso único é enviado ao e-mail e expira em
15 minutos. A conta só pode entrar depois da confirmação.

A recuperação de senha envia um link de uso único, válido por 30 minutos, para
o e-mail cadastrado. Configure o SMTP e defina
`DASHBOARD_PUBLIC_URL=https://news.venturi.vps-kinghost.net` no `.env` de
produção para o link apontar ao endereço público correto.

O relatório PDF aceita seções personalizadas e até três parágrafos de anotações
do analista.

## Como funciona

Edite `config/keywords.yaml` para acrescentar termos sem mudar Python. A classificação guarda as evidências que justificaram cada nota. Risco e tom são independentes: risco 10/5, neutro 0, quase negativo, quase positivo e positivo. Impacto considera quantidade de termos, risco e peso da fonte.

Google exige chave e mecanismo Programmable Search.

Para habilitar Instagram, não informe a senha da conta. São necessários:

1. conta Instagram profissional (Empresa ou Criador);
2. Página do Facebook vinculada à conta;
3. aplicativo em Meta for Developers associado ao mesmo negócio;
4. permissões aprovadas para leitura básica e pesquisa de hashtags;
5. token de acesso de longa duração;
6. ID numérico da conta profissional do Instagram.

Grave somente o token e o ID no `.env`, em `INSTAGRAM_ACCESS_TOKEN` e
`INSTAGRAM_USER_ID`, confirme a versão da Graph API em
`INSTAGRAM_GRAPH_VERSION` e então altere `instagram.enabled` para `true`.
Nunca envie token, senha ou segredo do aplicativo por chat ou para o Git.

Telefones só devem vir de páginas profissionais públicas, nunca de fontes privadas.

## Desenvolvimento local

```bash
python -m venv .venv
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload
```
