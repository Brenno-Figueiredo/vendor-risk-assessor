"""Fornecedores FICTÍCIOS com problemas plantados, para demonstração e testes. Nenhum nome ou CNPJ é real."""
from __future__ import annotations

import csv
import hashlib
import io
import os
from typing import Dict, List

from .model import Vendor
from .questions import CLAUSES
from .scoring import inherent, scope
from .validators import make_cnpj

REF = "2026-10-22"
VENDOR_HEADER = "id;nome;cnpj;servico;categoria;criticidade;dados;volume;acesso;exterior;paises;subcontrata;nuvem;contrato_inicio;contrato_fim;responsavel;ultima_avaliacao;incidentes_12m"

# id, nome, cnpj-base, servico, categoria, crit, dados, volume, acesso, exterior, paises, subc, nuvem, inicio, fim, responsavel, ultima, incidentes, qualidade
VENDORS = [
    ("f01", "Nuvem Exemplo Ltda", "10000001", "Hospedagem e banco de dados em nuvem", "nuvem", "alta", "sensiveis", "alto", "leitura", "sim", "Estados Unidos; Irlanda", "sim", "sim",
     "2024-02-01", "2027-01-31", "Equipe de TI", "2026-01-15", 0, "good"),
    ("f02", "Cobranca Segura Exemplo", "10000002", "Cobrança de inadimplentes", "cobranca", "alta", "comuns", "alto", "leitura", "nao", "", "sim", "nao",
     "2025-01-01", "2026-11-30", "Cobranca", "", 0, "none"),
    ("f03", "Callcenter Modelo S.A.", "10000003", "Atendimento ao cliente", "callcenter", "alta", "sensiveis", "medio", "privilegiado", "nao", "", "sim", "nao",
     "2023-06-01", "2027-06-01", "Operacoes", "2025-03-10", 2, "poor"),
    ("f04", "Papelaria Exemplo", "10000004", "Material de escritório", "outros", "baixa", "nenhum", "baixo", "nenhum", "nao", "", "nao", "nao",
     "2024-01-01", "2027-12-31", "Compras", "2025-06-01", 0, "good"),
    ("f05", "Consultoria TI Teste", "10000005", "Suporte e infraestrutura de TI", "consultoria", "media", "nenhum", "baixo", "privilegiado", "nao", "", "nao", "nao",
     "2022-01-01", "2026-09-30", "", "2024-06-10", 0, "partial"),
    ("f06", "Hospedagem Brasil Exemplo", "10000006", "Servidores dedicados", "nuvem", "alta", "comuns", "medio", "leitura", "nao", "", "nao", "sim",
     "2024-05-01", "2028-04-30", "Equipe de TI", "2026-05-20", 0, "good"),
    ("f07", "SaaS Credito Exemplo", "10000007", "Sistema de análise de crédito (SaaS)", "software", "alta", "sensiveis", "alto", "leitura", "nao", "", "sim", "sim",
     "2025-03-01", "2028-02-28", "Credito", "2026-02-02", 1, "mixed"),
    ("f08", "Marketing Digital Exemplo", "10000008", "Campanhas e e-mail marketing", "outros", "media", "comuns", "medio", "nenhum", "sim", "Irlanda", "sim", "sim",
     "2025-08-01", "2026-12-15", "Marketing", "2025-09-01", 0, "mixed"),
    ("f09", "Limpeza Exemplo", "10000009", "Limpeza predial", "outros", "baixa", "nenhum", "baixo", "nenhum", "nao", "", "nao", "nao",
     "2024-01-01", "2027-01-01", "Administrativo", "", 0, "none"),
    ("f10", "Processamento Dados Exemplo", "INVALIDO", "Processamento de folha e dados cadastrais", "processamento", "alta", "sensiveis", "alto", "privilegiado", "nao", "", "nao", "nao",
     "2021-01-01", "2027-01-01", "RH", "2025-01-20", 3, "mixed"),
    ("f11", "Hospedagem BR (cadastro duplicado)", "10000006", "Servidores dedicados", "nuvem", "baixa", "nenhum", "baixo", "nenhum", "nao", "", "nao", "nao",
     "2024-05-01", "2028-04-30", "Equipe de TI", "2026-05-20", 0, "none"),
]
OVERRIDES: Dict[str, Dict[str, str]] = {
    "f07": {"Q22": "nao", "Q25": "nao"},
    "f08": {"Q24": "nao", "Q23": "nao"},
    "f03": {"Q07": "nao"},
    "f10": {"Q27": "na_sem_justificativa"},
}
# cláusulas ausentes por fornecedor (os demais têm tudo). Fornecedores fora deste dicionário e sem entrada em NO_CLAUSE_ROWS têm tudo.
MISSING_CLAUSES = {"f01": ["C09"], "f03": ["C03", "C05", "C06", "C12"], "f07": ["C12", "C04"], "f08": ["C01", "C06"], "f10": ["C04", "C05", "C02"]}
NO_CLAUSE_ROWS = {"f02", "f04", "f05", "f09", "f11"}
EVIDENCE = "Evidência de exemplo (fictícia)"
GOOD_DATE = "2026-06-01"


def _h(vid: str, qid: str) -> int:
    return int(hashlib.sha1(f"{vid}{qid}".encode()).hexdigest(), 16) % 10


def _cnpj(base: str) -> str:
    if base == "INVALIDO":
        return "11.222.333/0001-99"                    # dígitos verificadores errados de propósito
    return make_cnpj(base.ljust(8, "0") + "0001")


def _line(cells) -> str:
    """Uma linha de CSV com o separador ';'. Campos que contêm ';' (como a lista de países) ganham aspas."""
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="").writerow(cells)
    return buf.getvalue()


def vendor_rows() -> List[str]:
    return [_line((v[0], v[1], _cnpj(v[2]), *v[3:18])) for v in VENDORS]


def _as_vendor(v) -> Vendor:
    from .model import parse_date
    return Vendor(v[0], v[1], _cnpj(v[2]), v[3], v[4], v[5], v[6], v[7], v[8], v[9] == "sim", v[10], v[11] == "sim", v[12] == "sim",
                  parse_date(v[13]), parse_date(v[14]), v[15], parse_date(v[16]), v[17])


def answer_rows() -> List[str]:
    rows = []
    for raw in VENDORS:
        vid, quality = raw[0], raw[18]
        if quality == "none":
            continue
        v = _as_vendor(raw)
        qs = scope(v, inherent(v)["tier"])
        if quality == "partial":
            qs = qs[:max(1, len(qs) // 2)]
        for q in qs:
            h = _h(vid, q.id)
            if quality == "good":
                resp, ev = "sim", True
            elif quality == "mixed":
                resp, ev = (("sim", True) if h <= 5 else ("sim", False) if h <= 7 else ("parcial", True) if h == 8 else ("nao", False))
            elif quality == "poor":
                resp, ev = (("sim", True) if h < 3 else ("sim", False) if h < 5 else ("parcial", True) if h < 7 else ("nao", False))
            else:  # partial
                resp, ev = ("sim", True) if h <= 6 else ("nao", False)
            over = OVERRIDES.get(vid, {}).get(q.id)
            if over == "na_sem_justificativa":
                resp, ev = "na", False
            elif over:
                resp, ev = over, False
            rows.append(_line((vid, q.id, resp, EVIDENCE if ev else "", GOOD_DATE if ev else "")))
    return rows


def clause_rows() -> List[str]:
    rows = []
    for raw in VENDORS:
        vid = raw[0]
        if vid in NO_CLAUSE_ROWS:
            continue
        v = _as_vendor(raw)
        tier = inherent(v)["tier"]
        for c in CLAUSES:
            if tier in c.required_for:
                rows.append(_line((vid, c.id, "nao" if c.id in MISSING_CLAUSES.get(vid, []) else "sim")))
    return rows


def write_samples(directory: str) -> List[str]:
    os.makedirs(directory, exist_ok=True)
    files = {"fornecedores.csv": [VENDOR_HEADER] + vendor_rows(), "respostas.csv": ["fornecedor;pergunta;resposta;evidencia;data_evidencia"] + answer_rows(),
             "clausulas.csv": ["fornecedor;clausula;presente"] + clause_rows()}
    for name, lines in files.items():
        with open(os.path.join(directory, name), "w", encoding="utf-8-sig", newline="") as f:
            f.write("\n".join(lines) + "\n")
    return list(files)
