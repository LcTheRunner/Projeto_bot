from app.classifier import classify

def test_risco_dez_e_contexto():
    result = classify("Polícia Federal investiga corrupção com O.S.", "Contrato da organização social com a prefeitura")
    assert result.risk_score == 10
    assert result.tone == "negativo"
    assert "O.S." in result.matched_keywords

def test_neutro():
    assert classify("ONG apresenta relatório", "A organização publicou dados anuais").risk_score == 0

def test_editoria():
    assert classify("ONG fecha parceria", "Investimento social no terceiro setor").section == "terceiro_setor"
