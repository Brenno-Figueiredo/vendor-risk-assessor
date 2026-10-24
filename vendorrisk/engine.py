"""Executa a avaliação de todos os fornecedores e monta o plano de ação."""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Dict, List, Optional

from .model import Answer, Dataset, Finding
from .questions import CLAUSES
from .rules import CFG_DEFAULTS, DUE_DAYS, RULES, Ctx
from .scoring import REVIEW_CYCLE_DAYS, assess_controls, inherent, level_of, residual_risk

RELEVANT_CATEGORIES = {"nuvem", "processamento", "armazenamento"}


def relevant_service(vendor, tier: str) -> bool:
    """Provável 'serviço relevante' de processamento/armazenamento/nuvem. A decisão final é da instituição e do jurídico."""
    return (vendor.nuvem or vendor.categoria in RELEVANT_CATEGORIES) and tier in ("critico", "alto")


def analyze(ds: Dataset, today: Optional[date] = None, cfg: Optional[Dict] = None) -> Dict:
    today = today or date.today()
    config = {**CFG_DEFAULTS, **(cfg or {})}
    by_vendor: Dict[str, Dict[str, Answer]] = {}
    for a in ds.answers:
        by_vendor.setdefault(a.vendor, {})[a.question] = a
    clause_map: Dict[str, Dict[str, str]] = {}
    if ds.clauses is not None:
        for c in ds.clauses:
            clause_map.setdefault(c.vendor, {})[c.clause] = c.presente
    results: List[Dict] = []
    findings: List[Finding] = []
    for v in ds.vendors.values():
        inh = inherent(v)
        tier = inh["tier"]
        assess = assess_controls(v, tier, by_vendor.get(v.id, {}), today)
        residual = residual_risk(inh["norm"], assess["effectiveness"])
        ctx = Ctx(v, tier, assess, by_vendor.get(v.id, {}), clause_map.get(v.id, {}) if ds.clauses is not None else None,
                  v.id in clause_map, today, config, ds.vendors)
        vf: List[Finding] = []
        for r in RULES:
            vf += r.func(ctx)
        next_review = (v.ultima_avaliacao + timedelta(days=REVIEW_CYCLE_DAYS[tier])) if v.ultima_avaliacao else None
        level = level_of(residual) if residual is not None else "sem_dados"
        if any(f.severity == "critical" for f in vf) and level in ("medio", "baixo", "sem_dados"):
            level = "alto"          # um achado crítico nunca deve ficar escondido atrás de uma boa nota geral
        results.append({"vendor": v, "inherent": inh, "tier": tier, "assess": assess, "residual": residual,
                        "level": level, "relevant": relevant_service(v, tier), "findings": vf, "next_review": next_review})
        findings += vf
    plan = build_plan(ds, findings, today)
    skipped = []
    if ds.clauses is None:
        skipped.append({"rule": "V07", "reason": "faltam dados: planilha de cláusulas do contrato (--clauses)"})
    notes = list(ds.notes)
    if not config["regulado_bcb"]:
        notes.append("modo 'sem Banco Central': as cláusulas C07, C08, C10 e C11 não são exigidas")
    results.sort(key=lambda r: (-(r["residual"] if r["residual"] is not None else 101), r["vendor"].nome))
    return {"today": today, "config": config, "results": results, "findings": findings, "plan": plan, "skipped": skipped, "notes": notes,
            "summary": summarize(results, findings, today)}


def build_plan(ds: Dataset, findings: List[Finding], today: date) -> List[Dict]:
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    plan = [{"vendor": f.vendor, "name": ds.vendors[f.vendor].nome, "owner": ds.vendors[f.vendor].responsavel or "(sem responsável)", "severity": f.severity,
             "rule": f.rule, "action": f.action, "detail": f.detail, "due": today + timedelta(days=DUE_DAYS[f.severity])} for f in findings]
    return sorted(plan, key=lambda p: (order[p["severity"]], p["due"], p["name"]))


def summarize(results: List[Dict], findings: List[Finding], today: date) -> Dict:
    by_sev = Counter(f.severity for f in findings)
    return {"vendors": len(results), "findings": len(findings),
            "by_tier": dict(Counter(r["tier"] for r in results)), "by_level": dict(Counter(r["level"] for r in results)),
            "by_severity": {s: by_sev.get(s, 0) for s in ("critical", "high", "medium", "low")}, "by_rule": dict(Counter(f.rule for f in findings)),
            "relevant": sum(1 for r in results if r["relevant"]),
            "overdue": sum(1 for r in results if r["next_review"] and r["next_review"] < today),
            "never_assessed": sum(1 for r in results if not r["assess"]["answered"])}
