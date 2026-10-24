"""Saídas: terminal, JSON, CSV (achados e plano de ação), painel HTML, ficha de cada fornecedor, ComplianceMap e feed do Venator.

Privacidade/confidencialidade: o relatório completo traz nomes de fornecedores e as fraquezas deles (confidencial). As exportações
para o ComplianceMap e o Venator são AGREGADAS: contagens por regra, sem nomes."""
from __future__ import annotations

import csv
import html
import io
import json
import time
from datetime import datetime
from typing import Dict, List

from .model import SEV_LABEL, TIER_LABEL
from .rules import RULES

ANSI = {"critical": "\033[1;97;41m", "high": "\033[1;31m", "medium": "\033[1;33m", "low": "\033[1;34m", "b": "\033[1m", "d": "\033[2m", "x": "\033[0m"}
COLOR = {"critical": "#ff5c7a", "high": "#ff9a45", "medium": "#f2cd3b", "low": "#5aa9ff", "critico": "#ff5c7a", "alto": "#ff9a45", "medio": "#f2cd3b",
         "baixo": "#3ddc84", "sem_dados": "#8ba2b4"}
LEVEL_SEV = {"critico": "critical", "alto": "high", "medio": "medium", "baixo": "low", "sem_dados": "low"}
CSV_PREFIX = ("=", "+", "-", "@", "\t", "\r")


def _safe(v):
    return ("'" + v) if isinstance(v, str) and v.startswith(CSV_PREFIX) else v


def _pct(x) -> str:
    return "—" if x is None else f"{round(100 * x)}%"


def _controls(r: Dict) -> str:
    """Eficácia dos controles; quem nunca respondeu aparece como 's/ resp.' (e o risco residual fica igual ao inerente, de forma conservadora)."""
    return "s/ resp." if not r["assess"]["answered"] else _pct(r["assess"]["effectiveness"])


def render_text(result: Dict, color: bool = False, top: int = 12) -> str:
    p = (lambda t, k: f"{ANSI[k]}{t}{ANSI['x']}") if color else (lambda t, k: t)
    s = result["summary"]
    lines = [p("AVALIAÇÃO DE RISCO DE FORNECEDORES", "b"), f"Data de referência: {result['today']:%d/%m/%Y}  ·  {s['vendors']} fornecedor(es), {s['findings']} achado(s)",
             "Por nível de risco residual: " + " · ".join(f"{TIER_LABEL.get(k, k)}: {s['by_level'].get(k, 0)}" for k in ("critico", "alto", "medio", "baixo", "sem_dados") if s['by_level'].get(k, 0)),
             f"{s['relevant']} serviço(s) provavelmente relevante(s) · {s['overdue']} reavaliação(ões) vencida(s) · {s['never_assessed']} sem respostas", "",
             p(f"{'FORNECEDOR':<34}{'NÍVEL':<9}{'INERENTE':>9}{'CONTROLES':>10}{'RESIDUAL':>9}  {'RISCO':<9}{'ACHADOS':>8}", "b")]
    for r in result["results"]:
        v, inh, lvl = r["vendor"], r["inherent"], r["level"]
        lines.append(f"{v.nome[:33]:<34}{TIER_LABEL[r['tier']]:<9}{inh['norm']:>9}{_controls(r):>10}"
                     f"{'—' if r['residual'] is None else r['residual']:>9}  {p(TIER_LABEL.get(lvl, 'Sem dados').ljust(9), LEVEL_SEV[lvl])}{len(r['findings']):>8}"
                     + ("  ★ relevante" if r["relevant"] else ""))
    lines += ["", p("Ações mais urgentes", "b")]
    for a in [x for x in result["plan"] if x["severity"] in ("critical", "high")][:top]:
        lines.append(f"{p('[' + SEV_LABEL[a['severity']] + ']', a['severity'])} {a['name']}: {a['detail'][:110]}")
        lines.append(p(f"    prazo {a['due']:%d/%m/%Y} · responsável: {a['owner']} · {a['action'][:90]}", "d"))
    if result["skipped"]:
        lines += ["", p("Regras puladas (faltam dados)", "b")] + [f"  {x['rule']}: {x['reason']}" for x in result["skipped"]]
    lines += [f"Nota: {n}" for n in result["notes"]]
    lines += ["", p("A nota ajuda a priorizar; a decisão sobre contratar, manter ou sair é humana. ★ = provável 'serviço relevante' (confirme com o jurídico).", "d")]
    return "\n".join(lines)


def vendor_text(r: Dict, today) -> str:
    v, inh, a = r["vendor"], r["inherent"], r["assess"]
    lines = [f"{v.nome} ({v.id})  CNPJ {v.cnpj or '—'}", f"Serviço: {v.servico or '—'}  ·  responsável: {v.responsavel or '—'}",
             f"Nível: {TIER_LABEL[r['tier']]} (inerente {inh['points']}/16)  ·  controles {_controls(r)}  ·  residual {r['residual'] if r['residual'] is not None else '—'}"
             f"  ·  risco {TIER_LABEL.get(r['level'], 'Sem dados')}", "Por que este nível: " + (", ".join(f"{k} (+{x})" for k, x in inh["parts"].items()) or "sem fatores de risco"), ""]
    if a["domain_pct"]:
        lines.append("Controles por tema: " + " · ".join(f"{d} {x}%" for d, x in sorted(a["domain_pct"].items(), key=lambda kv: kv[1])))
    lines.append("")
    for f in r["findings"]:
        lines.append(f"[{SEV_LABEL[f.severity]}] {f.rule} {f.title}: {f.detail}")
    if not r["findings"]:
        lines.append("Nenhum achado.")
    if r["next_review"]:
        late = r["next_review"] < today
        lines.append(f"\n{'Reavaliação VENCIDA desde' if late else 'Próxima reavaliação:'} {r['next_review']:%d/%m/%Y}")
    return "\n".join(lines)


def to_json(result: Dict) -> str:
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "reference_date": result["today"].isoformat(), "summary": result["summary"],
           "skipped": result["skipped"], "notes": result["notes"],
           "vendors": [{"id": r["vendor"].id, "nome": r["vendor"].nome, "tier": r["tier"], "inherent": r["inherent"], "effectiveness": r["assess"]["effectiveness"],
                        "residual": r["residual"], "level": r["level"], "relevant": r["relevant"], "answered": r["assess"]["answered"],
                        "in_scope": r["assess"]["in_scope"], "domain_pct": r["assess"]["domain_pct"],
                        "next_review": r["next_review"].isoformat() if r["next_review"] else None,
                        "findings": [f.to_dict() for f in r["findings"]]} for r in result["results"]]}
    return json.dumps(out, ensure_ascii=False, indent=2)


def findings_csv(result: Dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["fornecedor", "nome", "regra", "severidade", "titulo", "detalhe", "controles"])
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    names = {r["vendor"].id: r["vendor"].nome for r in result["results"]}
    for f in sorted(result["findings"], key=lambda x: (order[x.severity], x.vendor, x.rule)):
        w.writerow([_safe(f.vendor), _safe(names.get(f.vendor, "")), f.rule, f.severity, f.title, _safe(f.detail), " ".join(f.controls)])
    return buf.getvalue()


def plan_csv(result: Dict) -> str:
    """Plano de ação com prazo e responsável, com colunas em branco para acompanhamento."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\n")
    w.writerow(["prazo", "severidade", "fornecedor", "responsavel", "regra", "acao", "detalhe", "status", "observacao"])
    for a in result["plan"]:
        w.writerow([a["due"].isoformat(), a["severity"], _safe(a["name"]), _safe(a["owner"]), a["rule"], a["action"], _safe(a["detail"]), "", ""])
    return buf.getvalue()


_GROUPS = {"TER-01": "avaliação e diligência dos fornecedores", "TER-02": "cláusulas contratuais", "TER-03": "governança de nuvem",
           "TER-04": "incidentes de terceiros", "ACC-04": "acessos privilegiados de terceiros"}


def to_compliancemap(result: Dict, has_clauses: bool) -> str:
    """Evidência automática AGREGADA (sem nomes) no formato que o ComplianceMap lê com --auto."""
    findings = result["findings"]
    rows = []
    for control in _GROUPS:
        hits = [f for f in findings if control in f.controls]
        if control == "TER-02" and not has_clauses:
            rows.append({"check": "vendorrisk", "control": control, "status": "unknown", "detail": "planilha de cláusulas não informada", "platform": "tprm"})
            continue
        if control == "TER-03" and not any(r["vendor"].nuvem or r["relevant"] for r in result["results"]):
            rows.append({"check": "vendorrisk", "control": control, "status": "unknown", "detail": "sem fornecedores de nuvem no cadastro", "platform": "tprm"})
            continue
        if control == "ACC-04" and not any(r["vendor"].acesso == "privilegiado" for r in result["results"]):
            rows.append({"check": "vendorrisk", "control": control, "status": "unknown", "detail": "sem fornecedores com acesso privilegiado", "platform": "tprm"})
            continue
        counts = {}
        for f in hits:
            counts[f.rule] = counts.get(f.rule, 0) + 1
        rows.append({"check": "vendorrisk", "control": control, "status": "fail" if hits else "pass",
                     "detail": ("achados: " + ", ".join(f"{r} x{n}" for r, n in sorted(counts.items()))) if hits else "nenhum achado nas regras avaliadas",
                     "platform": "tprm"})
    return json.dumps({"collected_at": datetime.now().isoformat(timespec="seconds"), "system": "tprm",
                       "note": "Gerado pelo VendorRisk. Resultado agregado, sem nomes de fornecedores.", "results": rows}, ensure_ascii=False, indent=2)


def to_feed(result: Dict) -> List[Dict]:
    meta = {r.id: r for r in RULES}
    order = ["critical", "high", "medium", "low"]
    groups: Dict[str, list] = {}
    for f in result["findings"]:
        groups.setdefault(f.rule, []).append(f)
    now = time.time()
    return [{"ts": now, "source": "vendorrisk", "type": "generic", "ip": "", "severity": min((x.severity for x in fs), key=order.index),
             "message": f"Risco de terceiros: {len(fs)} ocorrência(s) de '{meta[rule].title}'"} for rule, fs in sorted(groups.items())]


CSS = """
:root{color-scheme:dark;--bg:#0b1118;--panel:#121b26;--line:#263a4b;--text:#e6eef5;--muted:#8ba2b4}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.55 "Segoe UI",system-ui,sans-serif}
main{max-width:1060px;margin:0 auto;padding:30px 22px 70px}h1{margin:0;font-size:26px}h2{font-size:17px;margin:28px 0 8px}.sub{color:var(--muted);margin:4px 0 0}
.top{display:flex;gap:12px;flex-wrap:wrap;margin:22px 0}.card{flex:1;min-width:140px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 18px}
.card b{display:block;font-size:30px;line-height:1.1}.card span{color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th{text-align:left;color:var(--muted);font-weight:500;padding:9px 10px;border-bottom:1px solid var(--line)}td{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.badge{font-size:11.5px;font-weight:700;border-radius:999px;padding:1px 9px;color:#07121b;white-space:nowrap}.muted{color:var(--muted);font-size:12.5px}
.bar{height:6px;background:#0a121a;border-radius:3px;margin-top:4px;overflow:hidden}.bar i{display:block;height:100%}
.f{background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:10px;padding:11px 14px;margin:8px 0}
code{font-family:ui-monospace,Consolas,monospace;font-size:12px}.note{color:var(--muted);font-size:12.5px;margin-top:30px;border-top:1px solid var(--line);padding-top:14px}
"""


def _badge(text: str, key: str) -> str:
    return f"<span class='badge' style='background:{COLOR.get(key, '#8ba2b4')}'>{html.escape(text)}</span>"


def render_html(result: Dict) -> str:
    e = html.escape
    s = result["summary"]
    rows = "".join(
        f"<tr><td><b>{e(r['vendor'].nome)}</b><div class='muted'>{e(r['vendor'].servico)}</div></td><td>{_badge(TIER_LABEL[r['tier']], r['tier'])}</td>"
        f"<td>{r['inherent']['norm']}<div class='bar'><i style='width:{r['inherent']['norm']}%;background:#8ba2b4'></i></div></td>"
        f"<td>{_controls(r)}</td><td>{'—' if r['residual'] is None else r['residual']}</td>"
        f"<td>{_badge(TIER_LABEL.get(r['level'], 'Sem dados'), r['level'])}{' ★' if r['relevant'] else ''}</td><td>{len(r['findings'])}</td></tr>"
        for r in result["results"])
    plan = "".join(
        f"<div class='f' style='border-left-color:{COLOR[a['severity']]}'>{_badge(SEV_LABEL[a['severity']], a['severity'])} <b>{e(a['name'])}</b> · {e(a['rule'])}"
        f"<div class='muted'>{e(a['detail'])}</div><div class='muted'>Prazo {a['due']:%d/%m/%Y} · responsável: {e(a['owner'])} · {e(a['action'])}</div></div>"
        for a in result["plan"] if a["severity"] in ("critical", "high"))
    notes = "".join(f"<p class='muted'>{e(n)}</p>" for n in result["notes"] + [f"{x['rule']}: {x['reason']}" for x in result["skipped"]])
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>VendorRisk - relatório</title><style>{CSS}</style></head><body><main>
<h1>VendorRisk</h1><p class="sub">Avaliação de risco de fornecedores · referência {result['today']:%d/%m/%Y} · gerado em {datetime.now():%d/%m/%Y %H:%M}</p>
<div class="top"><div class="card"><span>Fornecedores</span><b>{s['vendors']}</b></div>
<div class="card"><span>Risco crítico</span><b style="color:#ff5c7a">{s['by_level'].get('critico', 0)}</b></div>
<div class="card"><span>Risco alto</span><b style="color:#ff9a45">{s['by_level'].get('alto', 0)}</b></div>
<div class="card"><span>Reavaliação vencida</span><b>{s['overdue']}</b></div><div class="card"><span>Sem respostas</span><b>{s['never_assessed']}</b></div></div>
<h2>Fornecedores por risco residual</h2><table><tr><th>Fornecedor</th><th>Nível</th><th>Inerente</th><th>Controles</th><th>Residual</th><th>Risco</th><th>Achados</th></tr>{rows}</table>
<h2>Ações críticas e altas</h2>{plan or "<p class='sub'>Nenhuma.</p>"}{notes}
<p class="note">A nota ajuda a priorizar; a decisão sobre contratar, manter ou sair é humana. ★ = provável serviço relevante (confirme com o jurídico).
Este relatório descreve as fraquezas dos seus fornecedores: confidencial.</p></main></body></html>"""


def render_scorecard(r: Dict, today) -> str:
    e = html.escape
    v, inh, a = r["vendor"], r["inherent"], r["assess"]
    q_rows = "".join(
        f"<tr><td><code>{e(x['q'].id)}</code></td><td>{e(x['q'].domain)}</td><td>{e(x['q'].text)}</td><td>{x['q'].weight}</td>"
        f"<td>{e({'sim': 'Sim', 'sim_sem_evidencia': 'Sim, sem evidência válida', 'parcial': 'Parcial', 'nao': 'Não', 'sem_resposta': 'Sem resposta', 'na': 'Não se aplica', 'na_sem_justificativa': 'N/A sem justificativa'}[x['status']])}</td></tr>"
        for x in a["rows"])
    finds = "".join(f"<div class='f' style='border-left-color:{COLOR[f.severity]}'>{_badge(SEV_LABEL[f.severity], f.severity)} <b>{e(f.rule)} {e(f.title)}</b>"
                    f"<div class='muted'>{e(f.detail)}</div><div class='muted'>Ação: {e(f.action)}</div></div>" for f in r["findings"]) or "<p class='sub'>Nenhum achado.</p>"
    return f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ficha: {e(v.nome)}</title><style>{CSS}</style></head><body><main>
<h1>{e(v.nome)}</h1><p class="sub">{e(v.servico)} · CNPJ {e(v.cnpj or '—')} · responsável: {e(v.responsavel or '—')} · referência {today:%d/%m/%Y}</p>
<div class="top"><div class="card"><span>Nível</span><b>{e(TIER_LABEL[r['tier']])}</b></div><div class="card"><span>Controles</span><b>{_controls(r)}</b></div>
<div class="card"><span>Risco residual</span><b>{'—' if r['residual'] is None else r['residual']}</b></div><div class="card"><span>Risco</span><b style="color:{COLOR.get(r['level'], '#8ba2b4')}">{e(TIER_LABEL.get(r['level'], 'Sem dados'))}</b></div></div>
<p class="muted">Por que este nível: {e(', '.join(f'{k} (+{x})' for k, x in inh['parts'].items()) or 'sem fatores de risco')}</p>
<h2>Achados e ações</h2>{finds}<h2>Perguntas avaliadas</h2><table><tr><th>ID</th><th>Tema</th><th>Pergunta</th><th>Peso</th><th>Situação</th></tr>{q_rows}</table>
<p class="note">Ficha confidencial. A decisão sobre o fornecedor é humana.</p></main></body></html>"""
