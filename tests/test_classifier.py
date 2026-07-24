from app.classifier import classify, is_relevant

def test_risco_dez_e_contexto():
    result = classify("Polícia Federal investiga corrupção", "Deputado é alvo de operação")
    assert result.risk_score == 10
    assert result.tone == "negativo"
    assert "corrupção" in result.matched_keywords
    assert result.section == "integridade_corrupcao"

def test_neutro():
    assert classify("ONG apresenta relatório", "A organização publicou dados anuais").risk_score == 0
    assert not is_relevant("ONG apresenta relatório", "A organização publicou dados anuais")

def test_editoria():
    result = classify("Empresa anuncia investimento", "Patrocínio apoiará ONG do terceiro setor")
    assert is_relevant("Empresa anuncia investimento", "Patrocínio apoiará ONG do terceiro setor")
    assert result.section == "investimento_social_ambiental"

def test_edital_relacionado_e_oportunidade():
    result = classify("Edital aberto para projetos de esporte e lazer", "Inscrições abertas para organizações sociais")
    assert is_relevant("Edital aberto para projetos de esporte e lazer", "Inscrições abertas")
    assert result.section == "editais_oportunidades"
    assert result.tone == "positivo"
    assert result.impact_score >= 8

def test_edital_generico_e_futebol_sao_descartados():
    assert not is_relevant("Edital para compra de computadores", "Aquisição de equipamentos administrativos")
    assert not is_relevant("Edital público do Prouni", "Bolsas para cursos de graduação")
    assert not is_relevant("Time vence campeonato de futebol", "Torcida comemora a vitória no estádio")
    assert not is_relevant(
        "Montadora anuncia corte de custos",
        "A empresa apresentou seu balanço. " + ("Dados financeiros. " * 30) + "A sustentabilidade faz parte da estratégia.",
    )

def test_marica_com_esporte_e_relevante():
    result = classify("Maricá amplia projetos de esporte", "Prefeitura oferece atividades de lazer")
    assert is_relevant("Maricá amplia projetos de esporte", "Prefeitura oferece atividades de lazer")
    assert result.section == "marica_esporte"

def test_variacao_lei_rouanet():
    assert is_relevant("Novo edital da Lei Rounet", "Projetos culturais podem participar")
