import json, re, unicodedata
from dataclasses import dataclass
from pathlib import Path
import yaml

def yaml_config(name: str) -> dict:
    path = Path(__file__).resolve().parent.parent / "config" / name
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)

def normalize(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))

@dataclass
class Result:
    risk_score: int
    tone: str
    impact_score: float
    matched_keywords: list[str]
    evidence: list[str]
    section: str

def _contains(text: str, term: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(normalize(term)) + r"(?!\w)", text) is not None

def _hits(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _contains(text, term)]

def _near_hits(text: str, terms: list[str], contexts: list[str], distance: int = 220) -> list[str]:
    found: list[str] = []
    for term in terms:
        term_matches = list(re.finditer(r"(?<!\w)" + re.escape(normalize(term)) + r"(?!\w)", text))
        if not term_matches:
            continue
        for context in contexts:
            context_matches = list(re.finditer(r"(?<!\w)" + re.escape(normalize(context)) + r"(?!\w)", text))
            if any(
                max(left.start(), right.start()) - min(left.end(), right.end()) <= distance
                for left in term_matches
                for right in context_matches
            ):
                found.extend((term, context))
    return found

def monitored_hits(title: str, body: str, cfg: dict | None = None, extra_terms: list[str] | None = None) -> list[str]:
    cfg = cfg or yaml_config("keywords.yaml")
    text = normalize(f"{title}. {body}")
    found = _hits(text, cfg.get("monitorados", []))
    found.extend(_hits(text, extra_terms or []))
    for combination in cfg.get("combinacoes_monitoradas", []):
        found.extend(_near_hits(
            text,
            combination.get("termos", []),
            combination.get("contexto", []),
            int(combination.get("distancia_maxima", 220)),
        ))
    return sorted(set(found), key=normalize)

def is_relevant(title: str, body: str, extra_terms: list[str] | None = None) -> bool:
    return bool(monitored_hits(title, body, extra_terms=extra_terms))

def classify(title: str, body: str, source_weight: float = 1.0, extra_terms: list[str] | None = None) -> Result:
    cfg = yaml_config("keywords.yaml")
    text = normalize(f"{title}. {body}")
    monitored = monitored_hits(title, body, cfg, extra_terms)
    evidence, hits, risk, opportunity, tone = [], [], 0, 0, "neutro"
    if monitored:
        evidence.append(f"monitoramento: {', '.join(monitored)}")
    for name, rule in cfg["regras"].items():
        found = _hits(text, rule["palavras"])
        if not found: continue
        hits += found
        evidence.append(f"{name}: {', '.join(found)}")
        polarity = rule.get("polaridade")
        if name.startswith("risco_"):
            risk = max(risk, int(rule["peso"])); tone = "negativo"
        elif polarity == "positiva" and tone != "negativo":
            opportunity = max(opportunity, int(rule["peso"]))
            tone = "positivo" if rule["peso"] else "quase_positivo"
        elif polarity == "negativa" and risk == 0:
            tone = "quase_negativo"
    if not monitored: evidence.append("sem termo monitorado")
    scores = {s: sum(_contains(text, w) for w in words) for s, words in cfg["editorias"].items()}
    section = max(scores, key=scores.get) if max(scores.values(), default=0) else "nao_identificada"
    signal = max(risk, opportunity)
    impact = round(min(10.0, source_weight * (1 + len(set(monitored)) + signal / 2)), 2)
    return Result(risk, tone, impact, sorted(set(monitored + hits)), evidence, section)

def result_json(result: Result):
    return json.dumps(result.matched_keywords, ensure_ascii=False), json.dumps(result.evidence, ensure_ascii=False)
