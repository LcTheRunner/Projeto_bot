from bs4 import BeautifulSoup

from app.collectors import _extract_author


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
