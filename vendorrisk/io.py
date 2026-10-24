"""Leitura dos CSVs. Tolerante com o que o Excel brasileiro faz: ';' como separador, BOM e codificação cp1252."""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from typing import Dict, List, Optional

from .model import Answer, ClauseRecord, Dataset, Vendor, norm, parse_date, to_int, yes

MAX_BYTES = 50 * 1024 * 1024


class DataError(ValueError):
    """Arquivo de entrada inválido (colunas faltando, tamanho, formato)."""


ALIASES = {
    "id": ["id", "fornecedor", "codigo", "cod", "id_fornecedor"],
    "nome": ["nome", "razao_social", "fornecedor_nome", "empresa"],
    "cnpj": ["cnpj"],
    "servico": ["servico", "objeto", "descricao_servico", "servico_prestado"],
    "categoria": ["categoria", "tipo", "tipo_servico"],
    "criticidade": ["criticidade", "criticidade_negocio", "impacto"],
    "dados": ["dados", "dados_pessoais", "tipo_dados", "trata_dados"],
    "volume": ["volume", "volume_dados", "volume_titulares"],
    "acesso": ["acesso", "acesso_sistemas", "acesso_aos_sistemas"],
    "exterior": ["exterior", "dados_no_exterior", "servico_no_exterior"],
    "paises": ["paises", "pais", "regioes", "paises_regioes"],
    "subcontrata": ["subcontrata", "subcontratacao", "usa_subcontratados"],
    "nuvem": ["nuvem", "servico_nuvem", "cloud"],
    "contrato_inicio": ["contrato_inicio", "inicio_contrato", "inicio", "vigencia_inicio"],
    "contrato_fim": ["contrato_fim", "fim_contrato", "fim", "vigencia_fim", "vencimento"],
    "responsavel": ["responsavel", "gestor", "responsavel_interno", "dono"],
    "ultima_avaliacao": ["ultima_avaliacao", "avaliado_em", "data_avaliacao"],
    "incidentes_12m": ["incidentes_12m", "incidentes", "incidentes_ultimos_12_meses"],
    "pergunta": ["pergunta", "questao", "id_pergunta", "controle"],
    "resposta": ["resposta", "answer", "atende"],
    "evidencia": ["evidencia", "evidence", "comprovacao", "justificativa"],
    "data_evidencia": ["data_evidencia", "data_da_evidencia", "evidencia_data", "data"],
    "clausula": ["clausula", "id_clausula"],
    "presente": ["presente", "existe", "consta", "atende"],
}


def _header(h: str) -> str:
    s = unicodedata.normalize("NFKD", h or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def read_rows(path: str, required: List[str], label: str, wanted: List[str]) -> List[Dict[str, str]]:
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_BYTES + 1)
    except OSError as exc:
        raise DataError(f"{label}: não foi possível abrir '{path}' ({exc.strerror})") from None
    if len(raw) > MAX_BYTES:
        raise DataError(f"{label}: arquivo maior que 50 MB")
    text = decode(raw)
    first = text.splitlines()[0] if text.strip() else ""
    delim = max((";", ",", "\t"), key=first.count)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = [_header(h) for h in next(reader)]
    except StopIteration:
        raise DataError(f"{label}: arquivo vazio") from None
    column: Dict[str, int] = {}
    for canonical in wanted:
        for alias in ALIASES[canonical]:
            if alias in header:
                column[canonical] = header.index(alias)
                break
    missing = [c for c in required if c not in column]
    if missing:
        raise DataError(f"{label}: faltam as colunas {', '.join(missing)}. Colunas encontradas: {', '.join(h for h in header if h)}")
    return [{c: (line[i].strip() if i < len(line) else "") for c, i in column.items()}
            for line in reader if any(cell.strip() for cell in line)]


def _level(value: str, options: Dict[str, str], default: str) -> str:
    t = norm(value)
    return options.get(t, default) if t else default


CRIT = {"alta": "alta", "alto": "alta", "critica": "alta", "critico": "alta", "media": "media", "medio": "media", "baixa": "baixa", "baixo": "baixa"}
DADOS = {"nenhum": "nenhum", "nao": "nenhum", "sem": "nenhum", "comuns": "comuns", "comum": "comuns", "sim": "comuns", "pessoais": "comuns",
         "sensiveis": "sensiveis", "sensivel": "sensiveis", "sensitive": "sensiveis"}
VOL = {"baixo": "baixo", "baixa": "baixo", "medio": "medio", "media": "medio", "alto": "alto", "alta": "alto"}
ACESSO = {"nenhum": "nenhum", "nao": "nenhum", "leitura": "leitura", "consulta": "leitura", "privilegiado": "privilegiado",
          "admin": "privilegiado", "administrador": "privilegiado", "escrita": "privilegiado"}
RESP = {"sim": "sim", "s": "sim", "yes": "sim", "atende": "sim", "parcial": "parcial", "parcialmente": "parcial", "nao": "nao", "n": "nao",
        "no": "nao", "na": "na", "n/a": "na", "nao se aplica": "na"}
PRES = {"sim": "sim", "s": "sim", "presente": "sim", "parcial": "parcial", "nao": "nao", "n": "nao", "ausente": "nao", "na": "na", "n/a": "na"}


def load_vendors(path: str) -> Dict[str, Vendor]:
    cols = ["id", "nome", "cnpj", "servico", "categoria", "criticidade", "dados", "volume", "acesso", "exterior", "paises", "subcontrata", "nuvem",
            "contrato_inicio", "contrato_fim", "responsavel", "ultima_avaliacao", "incidentes_12m"]
    out: Dict[str, Vendor] = {}
    for r in read_rows(path, ["id", "nome"], "fornecedores", cols):
        vid = norm(r["id"])
        if not vid:
            continue
        out[vid] = Vendor(vid, r["nome"], r.get("cnpj", ""), r.get("servico", ""), norm(r.get("categoria", "")),
                          _level(r.get("criticidade", ""), CRIT, "media"), _level(r.get("dados", ""), DADOS, "nenhum"),
                          _level(r.get("volume", ""), VOL, "baixo"), _level(r.get("acesso", ""), ACESSO, "nenhum"),
                          bool(yes(r.get("exterior"))), r.get("paises", ""), bool(yes(r.get("subcontrata"))), bool(yes(r.get("nuvem"))),
                          parse_date(r.get("contrato_inicio")), parse_date(r.get("contrato_fim")), r.get("responsavel", ""),
                          parse_date(r.get("ultima_avaliacao")), to_int(r.get("incidentes_12m")))
    return out


def load_answers(path: str) -> List[Answer]:
    cols = ["id", "pergunta", "resposta", "evidencia", "data_evidencia"]
    return [Answer(norm(r["id"]), r["pergunta"].strip().upper(), _level(r.get("resposta", ""), RESP, ""), r.get("evidencia", ""),
                   parse_date(r.get("data_evidencia")))
            for r in read_rows(path, ["id", "pergunta"], "respostas", cols) if norm(r["id"])]


def load_clauses(path: str) -> List[ClauseRecord]:
    return [ClauseRecord(norm(r["id"]), r["clausula"].strip().upper(), _level(r.get("presente", ""), PRES, ""))
            for r in read_rows(path, ["id", "clausula"], "cláusulas", ["id", "clausula", "presente"]) if norm(r["id"])]


def load_dataset(vendors: str, answers: Optional[str] = None, clauses: Optional[str] = None) -> Dataset:
    ds = Dataset(load_vendors(vendors), load_answers(answers) if answers else [], load_clauses(clauses) if clauses else None)
    unknown = sorted({a.vendor for a in ds.answers} - set(ds.vendors))
    if unknown:
        ds.notes.append(f"{len(unknown)} fornecedor(es) com respostas não constam no cadastro (ignorados): {', '.join(unknown[:5])}")
    return ds
