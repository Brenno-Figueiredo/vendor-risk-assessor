"""Regras que transformam as respostas, o contrato e o cadastro em achados e ações. Cada achado vira uma ação com prazo."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from .model import TIER_LABEL, Finding, Vendor, norm
from .questions import CLAUSES, CLAUSE_BY_ID
from .scoring import REVIEW_CYCLE_DAYS
from .validators import valid_cnpj

CFG_DEFAULTS = {"expiry_days": 90, "regulado_bcb": True}
DUE_DAYS = {"critical": 30, "high": 60, "medium": 90, "low": 180}


@dataclass
class Ctx:
    vendor: Vendor
    tier: str
    assess: Dict
    answers: Dict
    clauses: Dict            # id da cláusula -> sim | parcial | nao | na ; None quando não há planilha de cláusulas
    has_clause_rows: bool
    today: object
    cfg: Dict
    all_vendors: Dict

    def state(self, qid: str) -> str:
        """sim_ok | sim_sem_evidencia | parcial | nao | sem_resposta | na | fora_de_escopo"""
        for r in self.assess["rows"]:
            if r["q"].id == qid:
                return "sim_ok" if r["status"] == "sim" else r["status"]
        return "fora_de_escopo"

    def clause_missing(self, cid: str) -> bool:
        return self.clauses is not None and self.clauses.get(cid, "") in ("", "nao")


@dataclass(frozen=True)
class RuleDef:
    id: str
    title: str
    severity: str
    why: str
    fix: str
    controls: tuple
    func: Callable
    needs: tuple = ()


RULES: List[RuleDef] = []


def rule(id, title, severity, why, fix, controls, needs=()):
    def deco(fn):
        RULES.append(RuleDef(id, title, severity, why, fix, tuple(controls), fn, tuple(needs)))
        return fn
    return deco


def _m(rid: str) -> RuleDef:
    return next(r for r in RULES if r.id == rid)


def F(rid: str, c: Ctx, detail: str, severity=None, title=None, controls=None) -> Finding:
    d = _m(rid)
    return Finding(rid, severity or d.severity, c.vendor.id, title or d.title, detail, d.fix, list(controls or d.controls))


@rule("V01", "Contrato vencido ou perto de vencer", "high",
      "Fornecedor sem contrato vigente atua sem as cláusulas de proteção, e contrato que vence sem plano deixa o serviço sem amparo.",
      "Renove com as cláusulas obrigatórias ou planeje a saída (migração e eliminação dos dados) antes do vencimento.", ("TER-02",))
def v01(c: Ctx):
    v, today = c.vendor, c.today
    if v.contrato_fim is None:
        return [F("V01", c, "contrato sem data de término registrada", "low")]
    if v.contrato_fim < today:
        return [F("V01", c, f"o contrato venceu em {v.contrato_fim:%d/%m/%Y} (há {(today - v.contrato_fim).days} dia(s)) e o fornecedor segue ativo",
                  "medium" if c.tier == "baixo" else "high")]
    left = (v.contrato_fim - today).days
    return [F("V01", c, f"o contrato vence em {left} dia(s) ({v.contrato_fim:%d/%m/%Y})", "medium")] if left <= c.cfg["expiry_days"] else []


@rule("V02", "Avaliação de risco vencida", "medium",
      "O risco do fornecedor muda com o tempo; o nível define a frequência mínima da reavaliação.",
      "Envie o questionário atualizado e reavalie o fornecedor.", ("TER-01",))
def v02(c: Ctx):
    v = c.vendor
    if v.ultima_avaliacao is None:
        return []
    age, cycle = (c.today - v.ultima_avaliacao).days, REVIEW_CYCLE_DAYS[c.tier]
    if age > cycle:
        return [F("V02", c, f"última avaliação há {age} dias (ciclo de {cycle} dias para o nível {TIER_LABEL[c.tier]})", "high" if c.tier == "critico" else "medium")]
    return []


@rule("V03", "Fornecedor sem avaliação", "high",
      "Contratar sem avaliar é o contrário da diligência prévia que a norma e as boas práticas pedem.",
      "Aplique o questionário do nível do fornecedor e registre as evidências.", ("TER-01",))
def v03(c: Ctx):
    v = c.vendor
    if v.ultima_avaliacao is None and not c.assess["answered"]:
        return [F("V03", c, "nunca foi avaliado (sem data de avaliação e sem respostas)", "high" if c.tier in ("critico", "alto") else "medium")]
    if v.ultima_avaliacao is None:
        return [F("V03", c, "há respostas, mas a data da última avaliação não está registrada", "low")]
    return []


@rule("V04", "Questionário incompleto", "medium",
      "Pergunta sem resposta é risco não avaliado.",
      "Cobre o fornecedor para responder as perguntas pendentes, com evidências.", ("TER-01",))
def v04(c: Ctx):
    a = c.assess
    if not a["in_scope"]:
        return []
    ratio = a["answered"] / a["in_scope"]
    if ratio >= 0.8:
        return []
    pending = [r["q"].id for r in a["rows"] if r["status"] in ("sem_resposta", "na_sem_justificativa")]
    return [F("V04", c, f"{a['answered']} de {a['in_scope']} perguntas respondidas; pendentes: {', '.join(pending[:8])}" + (" ..." if len(pending) > 8 else ""),
              "high" if c.tier == "critico" and ratio < 0.5 else "medium")]


@rule("V05", "Respostas 'sim' sem evidência válida", "medium",
      "Resposta sem prova vale pouco: 'sim' sem evidência (ou com evidência vencida) conta só metade.",
      "Peça a evidência (documento, relatório, print) com data dentro da validade.", ("TER-01",))
def v05(c: Ctx):
    weak = [r["q"].id for r in c.assess["rows"] if r["status"] == "sim_sem_evidencia"]
    if not weak:
        return []
    return [F("V05", c, f"{len(weak)} resposta(s) 'sim' sem evidência válida: {', '.join(weak[:8])}" + (" ..." if len(weak) > 8 else ""),
              "medium" if c.tier in ("critico", "alto") or len(weak) >= 3 else "low")]


_DEDICATED = {"Q07", "Q20", "Q23", "Q24", "Q30"}           # perguntas tratadas por regras próprias (V08 a V11)


@rule("V06", "Controle essencial não atendido", "high",
      "Um controle de peso máximo respondido 'não' é uma lacuna que o fornecedor admite ter.",
      "Exija um plano de ação com prazo ao fornecedor, ou aplique um controle compensatório.", ("TER-01",))
def v06(c: Ctx):
    out = []
    for r in c.assess["rows"]:
        q = r["q"]
        if r["status"] == "nao" and q.weight == 3 and q.id not in _DEDICATED:
            controls = ["TER-01"] + (["TER-04"] if q.id in ("Q13", "Q14") else []) + (["TER-02"] if q.id in ("Q22", "Q25") else [])
            out.append(F("V06", c, f"{q.id} ({q.domain}): {q.text}", controls=controls))
    return out


@rule("V07", "Contrato sem as cláusulas obrigatórias", "high",
      "As cláusulas de segurança e proteção de dados são o que obriga o fornecedor a cumprir o que prometeu.",
      "Negocie um aditivo com as cláusulas que faltam (modelo de aditivo de segurança e proteção de dados).", ("TER-02", "TER-03"), ("clausulas",))
def v07(c: Ctx):
    if c.clauses is None:
        return []
    required = [cl for cl in CLAUSES if c.tier in cl.required_for and (c.cfg["regulado_bcb"] or not cl.bcb_only)]
    if not c.has_clause_rows:
        return [F("V07", c, "contrato não analisado: nenhuma cláusula registrada para este fornecedor", "medium" if c.tier in ("critico", "alto") else "low")]
    missing = [cl for cl in required if c.clauses.get(cl.id, "") in ("", "nao")]
    partial = [cl for cl in required if c.clauses.get(cl.id, "") == "parcial"]
    out = []
    if missing:
        out.append(F("V07", c, "faltam: " + "; ".join(f"{cl.id} {cl.short}" for cl in missing),
                     "high" if c.tier in ("critico", "alto") else "medium"))
    if partial:
        out.append(F("V07", c, "parciais: " + "; ".join(f"{cl.id} {cl.short}" for cl in partial), "medium", "Cláusulas contratuais incompletas"))
    return out


@rule("V08", "Dados fora do Brasil sem salvaguardas comprovadas", "high",
      "Dados no exterior exigem base legal, país informado e cláusulas. Sem isso, há risco legal e de perda de controle.",
      "Documente países e regiões, a base legal da transferência e as salvaguardas contratuais.", ("TER-02", "TER-03"))
def v08(c: Ctx):
    if not c.vendor.exterior:
        return []
    issues = []
    if c.state("Q24") != "sim_ok":
        issues.append("transferência internacional sem base legal/salvaguardas comprovadas (Q24)")
    if c.state("Q23") not in ("sim_ok", "fora_de_escopo"):
        issues.append("países e regiões não documentados (Q23)")
    if c.clause_missing("C01"):
        issues.append("o contrato não indica países e regiões (C01)")
    return [F("V08", c, "; ".join(issues) + (f". Países informados: {c.vendor.paises}" if c.vendor.paises else ""))] if issues else []


@rule("V09", "Subcontratação sem controle", "medium",
      "O subcontratado também acessa os seus dados, e você pode nem saber quem é.",
      "Exija a lista de subcontratados, a notificação prévia de mudanças e o repasse das obrigações.", ("TER-01", "TER-02"))
def v09(c: Ctx):
    if not c.vendor.subcontrata:
        return []
    issues = []
    if c.state("Q20") != "sim_ok":
        issues.append("sem lista de subcontratados e aviso de mudanças comprovados (Q20)")
    if c.clause_missing("C06"):
        issues.append("sem cláusula de notificação da subcontratação (C06)")
    return [F("V09", c, "; ".join(issues), "high" if c.tier == "critico" and c.state("Q20") == "nao" else "medium")] if issues else []


@rule("V10", "Sem direito de acesso a relatórios e auditoria", "medium",
      "Sem acesso a certificações e relatórios, você não consegue monitorar o fornecedor nem provar a diligência.",
      "Inclua no contrato o acesso a relatórios de auditoria, certificações e informações de gestão do serviço.", ("TER-02",))
def v10(c: Ctx):
    if c.tier not in ("critico", "alto"):
        return []
    issues = []
    if c.state("Q30") in ("nao", "sem_resposta"):
        issues.append("o contrato não garante acesso a informações e relatórios (Q30)")
    if c.clause_missing("C05"):
        issues.append("a cláusula C05 não consta no contrato")
    return [F("V10", c, "; ".join(issues))] if issues else []


@rule("V11", "Acesso privilegiado sem controles comprovados", "high",
      "Fornecedor com acesso de administrador aos seus sistemas é um caminho direto para um incidente.",
      "Exija contas individuais, MFA e registro de uso, e revise esse acesso com frequência.", ("TER-01", "ACC-04"))
def v11(c: Ctx):
    if c.vendor.acesso != "privilegiado":
        return []
    s = c.state("Q07")
    if s == "nao":
        return [F("V11", c, "acesso privilegiado aos nossos sistemas SEM contas individuais, MFA e registro (Q07 = não)", "critical")]
    if s != "sim_ok":
        return [F("V11", c, "acesso privilegiado aos nossos sistemas sem comprovação de contas individuais, MFA e registro (Q07)")]
    return []


@rule("V12", "Incidentes recentes no fornecedor", "medium",
      "Incidente no fornecedor é incidente seu também: pode ter envolvido os seus dados.",
      "Peça o relatório do incidente (causa, impacto e correções) e reavalie o fornecedor.", ("TER-04",))
def v12(c: Ctx):
    n = c.vendor.incidentes_12m
    return [F("V12", c, f"{n} incidente(s) nos últimos 12 meses", "high" if n >= 3 else "medium")] if n > 0 else []


@rule("V13", "Fornecedor sem responsável interno", "low",
      "Sem dono interno, ninguém acompanha o contrato, os riscos e as ações pendentes.",
      "Designe um responsável interno pelo relacionamento e pelo risco do fornecedor.", ("TER-01",))
def v13(c: Ctx):
    return [] if c.vendor.responsavel.strip() else [F("V13", c, "nenhum responsável interno informado", "medium" if c.tier == "critico" else "low")]


@rule("V14", "CNPJ ausente ou inválido", "medium",
      "O CNPJ identifica o fornecedor para consultas oficiais e para o contrato. Dígito inválido indica erro de cadastro.",
      "Corrija o cadastro e confirme o CNPJ na Receita Federal.", ("TER-01",))
def v14(c: Ctx):
    v = c.vendor
    if not v.cnpj.strip():
        return [F("V14", c, "CNPJ não informado", "low")]
    return [] if valid_cnpj(v.cnpj) else [F("V14", c, f"CNPJ '{v.cnpj}' não passa nos dígitos verificadores")]


@rule("V15", "Cadastro duplicado", "low",
      "O mesmo CNPJ em dois cadastros duplica avaliações e esconde o risco real do fornecedor.",
      "Unifique os cadastros.", ("TER-01",))
def v15(c: Ctx):
    v = c.vendor
    key = "".join(ch for ch in v.cnpj.upper() if ch.isalnum())
    if not key:
        return []
    twins = [o.id for o in c.all_vendors.values() if o.id != v.id and "".join(ch for ch in o.cnpj.upper() if ch.isalnum()) == key]
    return [F("V15", c, "mesmo CNPJ do(s) cadastro(s): " + ", ".join(twins))] if twins else []


@rule("V16", "'Não se aplica' sem justificativa", "low",
      "Marcar 'não se aplica' sem explicar é uma forma de pular o controle.",
      "Peça a justificativa por escrito ou a resposta.", ("TER-01",))
def v16(c: Ctx):
    bad = [r["q"].id for r in c.assess["rows"] if r["status"] == "na_sem_justificativa" and r["q"].weight == 3]
    return [F("V16", c, "pergunta(s) essencial(is) marcada(s) 'não se aplica' sem justificativa: " + ", ".join(bad))] if bad else []
