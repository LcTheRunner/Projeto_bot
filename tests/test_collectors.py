from bs4 import BeautifulSoup
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from app.collectors import _extract_author, google_news_items, rss_items


def test_extrai_autor_de_json_ld():
    soup = BeautifulSoup(
        """
        <script type="application/ld+json">
          {"@type":"NewsArticle","author":{"@type":"Person","name":"Maria da Silva"}}
        </script>
        """,
        "html.parser",
    )
    assert _extract_author(soup) == "Maria da Silva"


def test_extrai_autor_de_metatag_e_remove_prefixo():
    soup = BeautifulSoup('<meta name="author" content="Por João Souza">', "html.parser")
    assert _extract_author(soup) == "João Souza"


def test_extrai_assinatura_visivel_depois_de_por():
    soup = BeautifulSoup(
        """
        <article><h1>Título</h1><p>Resumo da notícia.</p>
        <div>Por Redação g1</div>
        <time>28/07/2026 16h08 · Atualizado há 2 minutos</time></article>
        """,
        "html.parser",
    )
    assert _extract_author(soup) == "Redação g1"


def test_google_news_prioriza_consultas_globais_antes_do_limite(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "app.collectors.yaml_config",
        lambda name: {
            "google_news": {
                "enabled": True,
                "horas": 72,
                "queries": [f"consulta-{index}" for index in range(80)],
                "outlets": [],
            }
        },
    )
    monkeypatch.setattr(
        "app.collectors._feed_items",
        lambda name, url, weight, publisher_from_entry: calls.append(url) or [],
    )

    google_news_items(
        extra_queries=["palavra de usuário"],
        priority_queries=[
            '"Movimento Cultural Social"',
            '"Instituto Carioca"',
        ],
    )

    first_query = parse_qs(urlparse(calls[0]).query)["q"][0]
    second_query = parse_qs(urlparse(calls[1]).query)["q"][0]
    assert first_query.startswith('"Movimento Cultural Social"')
    assert second_query.startswith('"Instituto Carioca"')
    assert '"Instituto Carioca"' in second_query
    assert len(calls) == 80


def test_google_news_enriquece_apenas_candidatos_de_alerta_global(monkeypatch):
    monkeypatch.setattr(
        "app.collectors.yaml_config",
        lambda name: {
            "google_news": {
                "enabled": True,
                "horas": 72,
                "queries": ["consulta-comum"],
                "outlets": [],
            }
        },
    )
    monkeypatch.setattr(
        "app.collectors._feed_items",
        lambda name, url, weight, publisher_from_entry: [{
            "title": "Resultado",
            "body": "Resumo",
            "url": url,
            "source": name,
            "published_at": datetime.now(timezone.utc),
        }],
    )

    items = google_news_items(priority_queries=['"Instituto Carioca"'])

    assert items[0]["_global_alert_candidate"] is True
    assert items[0]["_skip_enrich"] is False
    assert items[1]["_global_alert_candidate"] is False
    assert items[1]["_skip_enrich"] is True


def test_rss_pode_marcar_itens_para_varredura_completa(monkeypatch):
    monkeypatch.setattr(
        "app.collectors.yaml_config",
        lambda name: {"rss": [{"nome": "Portal A", "url": "https://example.com/feed", "peso": 1}]},
    )
    monkeypatch.setattr(
        "app.collectors._feed_items",
        lambda *args, **kwargs: [{"url": "https://example.com/noticia"}],
    )

    item = rss_items(global_alert_scan=True)[0]

    assert item["_global_alert_candidate"] is True
    assert item["_skip_enrich"] is False
