"""Cálculo do risco: inerente (perfil do fornecedor), eficácia dos controles (respostas e evidências) e risco residual."""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from .model import Answer, Vendor
from .questions import QUESTIONS, Question

MAX_INHERENT = 16
RESIDUAL_LEVELS = ((55, "critico"), (35, "alto"), (18, "medio"), (0, "baixo"))
CONTROL_MAX_REDUCTION = 0.9      # nenhum fornecedor tem risco zero: controles perfeitos reduzem no máximo 90% do risco inerente
SCOPE_MIN_WEIGHT = {"critico": 1, "alto": 1, "medio": 2, "baixo": 3}      # fornecedores menos críticos recebem menos perguntas
EVIDENCE_MAX_AGE = {"critico": 365, "alto": 365, "medio": 540, "baixo": 730}
REVIEW_CYCLE_DAYS = {"critico": 365, "alto": 365, "medio": 730, "baixo": 1095}
CREDIT = {"sim_valid": 1.0, "sim_weak": 0.5, "parcial_valid": 0.5, "parcial_weak": 0.25, "nao": 0.0}


def inherent(v: Vendor) -> Dict:
    """Risco inerente: o quanto o fornecedor PODE nos prejudicar, antes de olhar os controles dele."""
    parts = {"criticidade do serviço": {"alta": 3, "media": 2, "baixa": 1}.get(v.criticidade, 2),
             "dados pessoais": {"sensiveis": 3, "comuns": 2, "nenhum": 0}.get(v.dados, 0)
             + (1 if v.volume == "alto" and v.dados != "nenhum" else 0),
             "acesso aos nossos sistemas": {"privilegiado": 3, "leitura": 1, "nenhum": 0}.get(v.acesso, 0),
             "dados fora do Brasil": 2 if v.exterior else 0, "subcontratação": 1 if v.subcontrata else 0,
             "serviço em nuvem": 1 if v.nuvem else 0,
             "incidentes recentes": 2 if v.incidentes_12m >= 3 else 1 if v.incidentes_12m >= 1 else 0}
    points = sum(parts.values())
    tier = "critico" if points >= 10 else "alto" if points >= 7 else "medio" if points >= 4 else "baixo"
    return {"points": points, "norm": round(100 * points / MAX_INHERENT), "tier": tier, "parts": {k: x for k, x in parts.items() if x}}


def level_of(residual: float) -> str:
    return next(level for floor, level in RESIDUAL_LEVELS if residual >= floor)


def scope(v: Vendor, tier: str) -> List[Question]:
    return [q for q in QUESTIONS if q.applies(v.tags) and q.weight >= SCOPE_MIN_WEIGHT[tier]]


def evidence_ok(a: Optional[Answer], today: date, max_age: int) -> bool:
    if a is None or not a.evidencia.strip() or a.data_evidencia is None:
        return False
    age = (today - a.data_evidencia).days
    return 0 <= age <= max_age


def assess_controls(v: Vendor, tier: str, answers: Dict[str, Answer], today: date) -> Dict:
    """Aplica a regra do projeto: sem evidência válida não há crédito completo."""
    max_age = EVIDENCE_MAX_AGE[tier]
    rows, total_w, gained = [], 0, 0.0
    for q in scope(v, tier):
        a = answers.get(q.id)
        status, credit, note = "sem_resposta", 0.0, ""
        if a is not None and a.resposta == "na" and a.evidencia.strip():
            rows.append({"q": q, "status": "na", "credit": None, "note": "não se aplica (justificado)", "answer": a})
            continue
        if a is not None and a.resposta in ("sim", "parcial", "nao"):
            valid = evidence_ok(a, today, max_age)
            if a.resposta == "nao":
                status, credit = "nao", CREDIT["nao"]
            elif a.resposta == "sim":
                status, credit = ("sim", CREDIT["sim_valid"]) if valid else ("sim_sem_evidencia", CREDIT["sim_weak"])
            else:
                status, credit = ("parcial", CREDIT["parcial_valid"]) if valid else ("parcial", CREDIT["parcial_weak"])
            if a.resposta != "nao" and not valid:
                note = "evidência ausente ou vencida" if a.evidencia.strip() or a.data_evidencia else "sem evidência"
        elif a is not None and a.resposta == "na":
            status, note = "na_sem_justificativa", "marcado como 'não se aplica' sem justificativa"
        rows.append({"q": q, "status": status, "credit": credit, "note": note, "answer": a})
        total_w += q.weight
        gained += q.weight * credit
    effectiveness = round(gained / total_w, 3) if total_w else None
    by_domain: Dict[str, List[float]] = {}
    for r in rows:
        if r["credit"] is not None:
            by_domain.setdefault(r["q"].domain, []).append((r["q"].weight, r["credit"]))
    domain_pct = {d: round(100 * sum(w * c for w, c in xs) / sum(w for w, _ in xs)) for d, xs in by_domain.items()}
    answered = sum(1 for r in rows if r["status"] in ("sim", "sim_sem_evidencia", "parcial", "nao"))
    return {"rows": rows, "effectiveness": effectiveness, "in_scope": len(rows), "answered": answered, "domain_pct": domain_pct,
            "max_age": max_age}


def residual_risk(inherent_norm: int, effectiveness: Optional[float]) -> Optional[int]:
    """Risco residual = risco inerente x (1 - eficácia dos controles x 0,9).
    Sem respostas a eficácia é 0, então o residual é igual ao inerente (conservador: o que não foi avaliado não reduz risco)."""
    if effectiveness is None:
        return None
    return round(inherent_norm * (1 - CONTROL_MAX_REDUCTION * effectiveness))
