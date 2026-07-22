# Monitor de Impacto Midiático

MVP em Python para coletar notícias, encontrar temas monitorados, classificar risco/tom/impacto e produzir estatísticas semanais por veículo, editoria e jornalista. O banco de produção é MariaDB; SQLite é usado automaticamente fora do Docker para facilitar testes.

## Executar com Docker

1. Copie `.env.example` para `.env`.
2. Preencha `GOOGLE_API_KEY` e `GOOGLE_CSE_ID` para habilitar Google Programmable Search.
3. Execute `docker compose up --build`.
4. Abra `http://localhost:8000/docs`.
5. Inicie uma coleta em `POST /coletas` ou aguarde a rotina diária das 04h30.

O relatório sai às 07h00 quando SMTP estiver preenchido. Também pode ser disparado por `POST /relatorios/enviar`. Para Instagram, informe conta profissional/token Meta e ative `instagram.enabled` em `config/sources.yaml`.

Consultas principais: `GET /noticias?risco=10` e `GET /estatisticas/semana?termo=corrupção com O.S.`.

## Como funciona

Edite `config/keywords.yaml` para acrescentar termos sem mudar Python. A classificação guarda as evidências que justificaram cada nota. Risco e tom são independentes: risco 10/5, neutro 0, quase negativo, quase positivo e positivo. Impacto considera quantidade de termos, risco e peso da fonte.

Google exige chave e mecanismo Programmable Search. Instagram exige conta profissional, aplicativo Meta aprovado e token; por isso permanece desligado até existirem credenciais. Telefones só devem vir de páginas profissionais públicas, nunca de fontes privadas.

## Desenvolvimento local

```bash
python -m venv .venv
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload
```
