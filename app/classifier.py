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

def classify(title: str, body: str, source_weight: float = 1.0) -> Result:
    cfg = yaml_config("keywords.yaml")
    text = normalize(f"{title}. {body}")
    monitored = [w for w in cfg["monitorados"] if _contains(text, w)]
    evidence, hits, risk, tone = [], [], 0, "neutro"
    for name, rule in cfg["regras"].items():
        found = [w for w in rule["palavras"] if _contains(text, w)]
        if not found: continue
        hits += found
        evidence.append(f"{name}: {', '.join(found)}")
        polarity = rule.get("polaridade")
        if name.startswith("risco_"):
            risk = max(risk, int(rule["peso"])); tone = "negativo"
        elif polarity == "positiva" and tone != "negativo":
            tone = "positivo" if rule["peso"] else "quase_positivo"
        elif polarity == "negativa" and risk == 0:
            tone = "quase_negativo"
    if not monitored: evidence.append("sem termo monitorado")
    scores = {s: sum(_contains(text, w) for w in words) for s, words in cfg["editorias"].items()}
    section = max(scores, key=scores.get) if max(scores.values(), default=0) else "nao_identificada"
    impact = round(min(10.0, source_weight * (1 + len(set(monitored)) + risk / 2)), 2)
    return Result(risk, tone, impact, sorted(set(monitored + hits)), evidence, section)

def result_json(result: Result):
    return json.dumps(result.matched_keywords, ensure_ascii=False), json.dumps(result.evidence, ensure_ascii=False)
