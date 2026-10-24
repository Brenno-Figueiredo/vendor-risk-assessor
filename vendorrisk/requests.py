"""Pedidos de informação: gera os questionários que você envia ao fornecedor e as planilhas para registrar as respostas."""
from __future__ import annotations

import csv
import io
import re
from typing import Dict, Optional

from .model import Dataset, norm
from .questions import CLAUSES
from .scoring import inherent, scope


def _csv(rows, header) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]+", "-", norm(text)).strip("-") or "fornecedor"


def build(ds: Dataset, only: Optional[str] = None, bcb: bool = True) -> Dict[str, str]:
    """Devolve {nome do arquivo: conteúdo}. Cada fornecedor recebe SÓ as perguntas do nível e do perfil dele."""
    files: Dict[str, str] = {}
    consolidated, clause_rows = [], []
    for v in ds.vendors.values():
        if only and v.id != norm(only):
            continue
        tier = inherent(v)["tier"]
        qs = scope(v, tier)
        files[f"questionario_{slug(v.id)}.csv"] = _csv(
            [[q.id, q.domain, q.text, q.weight, q.evidence, "", "", ""] for q in qs],
            ["pergunta", "tema", "texto", "peso", "evidencia_esperada", "resposta (sim/parcial/nao/na)", "evidencia", "data_evidencia"])
        consolidated += [[v.id, q.id, "", "", ""] for q in qs]
        clause_rows += [[v.id, c.id, ""] for c in CLAUSES if tier in c.required_for and (bcb or not c.bcb_only)]
    files["respostas_modelo.csv"] = _csv(consolidated, ["fornecedor", "pergunta", "resposta", "evidencia", "data_evidencia"])
    files["clausulas_modelo.csv"] = _csv(clause_rows, ["fornecedor", "clausula", "presente"])
    return files
