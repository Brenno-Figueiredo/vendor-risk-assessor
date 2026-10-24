"""Modelo de dados e utilitários de normalização."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

SEVERITIES = ("critical", "high", "medium", "low")
SEV_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1}
SEV_LABEL = {"critical": "Crítico", "high": "Alto", "medium": "Médio", "low": "Baixo"}
TIER_LABEL = {"critico": "Crítico", "alto": "Alto", "medio": "Médio", "baixo": "Baixo"}
TIERS = ("critico", "alto", "medio", "baixo")


def norm(text) -> str:
    s = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s).strip()


def parse_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def yes(value) -> Optional[bool]:
    t = norm(value)
    if t in ("sim", "s", "true", "1", "yes", "y", "x"):
        return True
    if t in ("nao", "n", "false", "0", "no"):
        return False
    return None


def to_int(value, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", ".").strip()))
    except ValueError:
        return default


@dataclass
class Vendor:
    id: str
    nome: str = ""
    cnpj: str = ""
    servico: str = ""
    categoria: str = ""              # nuvem | processamento | software | cobranca | callcenter | consultoria | outros
    criticidade: str = "media"       # alta | media | baixa (impacto no negócio se o serviço parar)
    dados: str = "nenhum"            # nenhum | comuns | sensiveis
    volume: str = "baixo"            # baixo | medio | alto
    acesso: str = "nenhum"           # nenhum | leitura | privilegiado (acesso aos NOSSOS sistemas)
    exterior: bool = False
    paises: str = ""
    subcontrata: bool = False
    nuvem: bool = False
    contrato_inicio: Optional[date] = None
    contrato_fim: Optional[date] = None
    responsavel: str = ""
    ultima_avaliacao: Optional[date] = None
    incidentes_12m: int = 0

    @property
    def tags(self) -> set:
        t = {"always"}
        if self.dados != "nenhum":
            t.add("dados")
        if self.dados == "sensiveis":
            t.add("sensiveis")
        if self.nuvem:
            t.add("nuvem")
        if self.acesso != "nenhum":
            t.add("acesso")
        if self.acesso == "privilegiado":
            t.add("privilegiado")
        if self.exterior:
            t.add("exterior")
        if self.subcontrata:
            t.add("subcontrata")
        return t


@dataclass
class Answer:
    vendor: str
    question: str
    resposta: str = ""               # sim | parcial | nao | na
    evidencia: str = ""
    data_evidencia: Optional[date] = None


@dataclass
class ClauseRecord:
    vendor: str
    clause: str
    presente: str = ""               # sim | parcial | nao | na


@dataclass
class Dataset:
    vendors: Dict[str, Vendor]
    answers: List[Answer] = field(default_factory=list)
    clauses: Optional[List[ClauseRecord]] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class Finding:
    rule: str
    severity: str
    vendor: str
    title: str
    detail: str
    action: str = ""
    controls: List[str] = field(default_factory=list)      # controles do ComplianceMap

    def to_dict(self) -> Dict:
        return {"rule": self.rule, "severity": self.severity, "vendor": self.vendor, "title": self.title,
                "detail": self.detail, "action": self.action, "controls": self.controls}
