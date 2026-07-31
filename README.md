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
As 18 palavras-chave oficiais são entregues por padrão a todas as contas,
incluindo **Movimento Cultural Social** e **Instituto Carioca**, mas cada usuário pode
removê-las. A tela aceita inclusão e remoção em lote, elimina
duplicatas e reconhece vírgula, ponto, ponto e vírgula, dois-pontos, aspas e
quebras de linha como separadores.

O dashboard abre em **Brasil inteiro**. O seletor de abrangência no recorte compartilhado
tem busca textual e permite selecionar todo o Estado do Rio de Janeiro ou
combinar livremente vários dos 92 municípios fluminenses, incluindo
**Rio de Janeiro (capital)**, sem alterar a coleta nacional.

O período do painel pode ser alterado entre **24 horas**, **48 horas**, **7
dias** e **30 dias**. O mesmo período é usado nos indicadores, notícias e no
relatório PDF.

Palavras-chave, veículos, editorias, riscos, tons e localidades aceitam seleção
múltipla. Esse recorte permanece sincronizado entre Visão geral,
Palavras-chave, Veículos, Notícias e o relatório PDF. A página de Veículos usa
o mesmo recorte para mostrar quais fontes mais publicaram sobre o assunto. Os
filtros do formulário de Envios por e-mail permanecem independentes. A busca
livre por assunto, título, jornalista ou expressão também integra esse recorte.

No cadastro, um código numérico de uso único é enviado ao e-mail e expira em
15 minutos. A conta só pode entrar depois da confirmação.

A recuperação de senha envia um link de uso único, válido por 30 minutos, para
o e-mail cadastrado. Configure o SMTP e defina
`DASHBOARD_PUBLIC_URL=https://news.venturi.vps-kinghost.net` no `.env` de
produção para o link apontar ao endereço público correto.

O relatório PDF aceita seções personalizadas e até três parágrafos de
**Parecer Técnico**.

Cada usuário também pode abrir **Envios por e-mail** no menu, escolher data,
horário, risco e um conjunto de palavras-chave e programar até dois boletins
ativos. Por padrão, o destino é sempre o e-mail verificado da própria conta.
Somente o proprietário configurado pode liberar individualmente uma conta para
informar outro endereço no agendamento; a opção permanece invisível e a API
recusa destinos externos enquanto essa permissão estiver bloqueada. O worker
atualiza a coleta até 20 minutos antes do horário e envia um resumo editorial
com no máximo seis notícias das últimas 24 horas que correspondam ao recorte.

## Administração de contas

A página `/admin` aparece somente para contas administrativas. Esconder o link
não é usado como mecanismo de segurança: listagem, criação, exclusão e
transferência de propriedade são revalidadas no backend em cada requisição.
Contas comuns recebem HTTP 403 mesmo que tentem chamar a API diretamente.

O proprietário permitido é definido pela combinação exata de
`DASHBOARD_OWNER_USERNAME` e `DASHBOARD_OWNER_EMAIL`. As duas variáveis são
obrigatórias e a conta correspondente precisa estar ativa e com o e-mail
confirmado. Na inicialização, essa conta é promovida automaticamente como
administradora única e a função administrativa é removida das demais contas.
O sistema não usa nem armazena a senha do proprietário nessa configuração.

Um administrador existente também pode acionar a transferência pela página.
Ela só é aceita para a mesma combinação de usuário e e-mail configurada no
servidor. O formulário da página cria somente usuários comuns.

Na mesma página, somente a conta proprietária pode habilitar ou revogar a
permissão de destino externo de cada usuário. Contas novas e existentes começam
com essa permissão bloqueada. A revogação impede novos usos e marca como falhos
os envios externos ainda pendentes.

Depois de alterar essas variáveis, recrie o contêiner para que o novo ambiente
seja carregado:

```bash
docker compose -f docker-compose.vps.yml up -d --build --force-recreate dashboard-api
```

O log do `dashboard-api` informa, sem exibir o e-mail, se o proprietário foi
confirmado como administrador único ou se a conta correspondente não foi
encontrada.

A exclusão é permanente, não permite remover a própria conta nem o último
administrador e também remove sessões, palavras-chave e agendamentos vinculados
por integridade referencial.

## Alertas institucionais

As expressões **Movimento Cultural Social** e **Instituto Carioca** são monitoradas
globalmente e não dependem das palavras-chave pessoais. O worker executa uma
busca prioritária no Google Notícias e nos feeds RSS configurados a cada 15
minutos, além da coleta normal. Na coleta diária, o conteúdo completo dos itens
RSS também é verificado, mesmo quando a menção não aparece no título ou no
resumo. Os termos são tratados como expressões completas para não acionar o
sino por fragmentos de outras palavras ou identificadores técnicos.

Quando uma ocorrência é encontrada, o sistema preserva por **90 dias** um
resumo próprio do alerta, mesmo depois que a notícia sai da janela operacional
de 72 horas. Todos os usuários autenticados enxergam o mesmo histórico pelo
sino do cabeçalho, mas o estado lido/não lido pertence exclusivamente a cada
conta. Alertas anteriores à criação de uma conta aparecem no histórico sem
inflar seu contador de não lidos. O painel consulta novas ocorrências a cada
minuto, permite marcar uma notícia ou todo o histórico como lido e abre o
endereço original em uma nova aba.

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
