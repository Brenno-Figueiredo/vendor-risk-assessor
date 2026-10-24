"""Linha de comando do VendorRisk."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from . import __version__, report, requests as rq
from .engine import analyze
from .io import DataError, load_dataset
from .model import SEV_WEIGHT, norm, parse_date
from .questions import CLAUSES, QUESTIONS
from .rules import RULES

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vendorrisk", description="Avaliação de risco de fornecedores (terceiros): nível, controles, cláusulas e plano de ação.",
                                 epilog="A nota ajuda a priorizar; a decisão é humana. Os relatórios descrevem fraquezas de fornecedores: confidenciais.")
    sub = ap.add_subparsers(dest="cmd")
    a = sub.add_parser("assess", help="avalia os fornecedores")
    a.add_argument("--vendors", required=True, metavar="fornecedores.csv")
    a.add_argument("--answers", metavar="respostas.csv")
    a.add_argument("--clauses", metavar="clausulas.csv", help="checklist das cláusulas do contrato por fornecedor")
    _opts(a)
    dm = sub.add_parser("demo", help="avalia os fornecedores FICTÍCIOS de exemplo")
    dm.add_argument("--dir", default=SAMPLES)
    _opts(dm)
    sh = sub.add_parser("show", help="mostra a ficha de um fornecedor")
    sh.add_argument("id")
    sh.add_argument("--vendors", metavar="fornecedores.csv")
    sh.add_argument("--answers", metavar="respostas.csv")
    sh.add_argument("--clauses", metavar="clausulas.csv")
    sh.add_argument("--today", metavar="AAAA-MM-DD")
    sh.add_argument("--demo", action="store_true", help="usa os dados de exemplo")
    rq_ = sub.add_parser("request", help="gera os questionários para enviar aos fornecedores e as planilhas de resposta")
    rq_.add_argument("--vendors", required=True, metavar="fornecedores.csv")
    rq_.add_argument("--out", default="pedidos")
    rq_.add_argument("--only", metavar="ID")
    rq_.add_argument("--no-bcb", action="store_true")
    sub.add_parser("questions", help="lista o banco de perguntas")
    sub.add_parser("clauses", help="lista as cláusulas de contrato verificadas")
    sub.add_parser("rules", help="lista as regras")
    ex = sub.add_parser("explain", help="explica uma regra")
    ex.add_argument("id")
    sm = sub.add_parser("samples", help="gera os CSVs de exemplo (fictícios)")
    sm.add_argument("--dir", default=SAMPLES)
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap


def _opts(p) -> None:
    p.add_argument("--today", metavar="AAAA-MM-DD", help="data de referência (padrão: hoje)")
    p.add_argument("--no-bcb", action="store_true", help="a contratante NÃO é supervisionada pelo Banco Central (dispensa as cláusulas C07, C08, C10 e C11)")
    p.add_argument("--json", metavar="ARQ.json")
    p.add_argument("--csv", metavar="ARQ.csv", help="todos os achados")
    p.add_argument("--plan", metavar="ARQ.csv", help="plano de ação com prazo e responsável")
    p.add_argument("--html", metavar="ARQ.html")
    p.add_argument("--scorecards", metavar="PASTA", help="uma ficha HTML por fornecedor")
    p.add_argument("--compliancemap", metavar="ARQ.json", help="evidência agregada para o ComplianceMap (--auto)")
    p.add_argument("--feed", metavar="ARQ.jsonl", help="eventos agregados para o Venator e o CorrelAI")
    p.add_argument("--fail-on", choices=["critical", "high", "medium", "low"])
    p.add_argument("--no-color", action="store_true")


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8-sig" if path.endswith(".csv") else "utf-8", newline="") as f:
        f.write(text)
    print(f"\nSalvo em: {path}")


def _run(a, ds, today) -> int:
    result = analyze(ds, today, {"regulado_bcb": not a.no_bcb})
    print(report.render_text(result, color=not a.no_color and sys.stdout.isatty()))
    for path, make in ((a.json, lambda: report.to_json(result)), (a.csv, lambda: report.findings_csv(result)), (a.plan, lambda: report.plan_csv(result)),
                       (a.html, lambda: report.render_html(result)), (a.compliancemap, lambda: report.to_compliancemap(result, ds.clauses is not None))):
        if path:
            _write(path, make())
    if a.feed:
        events = report.to_feed(result)
        with open(a.feed, "w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        print(f"{len(events)} evento(s) agregado(s) para o Venator/CorrelAI salvos em: {a.feed}")
    if a.scorecards:
        os.makedirs(a.scorecards, exist_ok=True)
        for r in result["results"]:
            with open(os.path.join(a.scorecards, f"ficha_{rq.slug(r['vendor'].id)}.html"), "w", encoding="utf-8") as f:
                f.write(report.render_scorecard(r, result["today"]))
        print(f"\n{len(result['results'])} ficha(s) salvas em: {a.scorecards}")
    if a.fail_on and any(SEV_WEIGHT[f.severity] >= SEV_WEIGHT[a.fail_on] for f in result["findings"]):
        return 1
    return 0


def _date(a):
    if not getattr(a, "today", None):
        return date.today()
    d = parse_date(a.today)
    if not d:
        raise DataError("data de referência inválida. Use AAAA-MM-DD.")
    return d


def cmd_assess(a) -> int:
    try:
        return _run(a, load_dataset(a.vendors, a.answers, a.clauses), _date(a))
    except DataError as exc:
        print(f"Erro nos dados: {exc}", file=sys.stderr)
        return 2


def cmd_demo(a) -> int:
    from .samples import REF, write_samples
    write_samples(a.dir)
    p = lambda n: os.path.join(a.dir, n)  # noqa: E731
    print(f"DEMONSTRAÇÃO com fornecedores FICTÍCIOS (dados de {a.dir}/)\n")
    return _run(a, load_dataset(p("fornecedores.csv"), p("respostas.csv"), p("clausulas.csv")), parse_date(a.today) if a.today else parse_date(REF))


def cmd_show(a) -> int:
    try:
        if a.demo:
            from .samples import REF, write_samples
            import tempfile
            with tempfile.TemporaryDirectory() as d:
                write_samples(d)
                ds = load_dataset(os.path.join(d, "fornecedores.csv"), os.path.join(d, "respostas.csv"), os.path.join(d, "clausulas.csv"))
            today = parse_date(REF)
        else:
            if not a.vendors:
                print("Informe --vendors (ou use --demo).", file=sys.stderr)
                return 2
            ds, today = load_dataset(a.vendors, a.answers, a.clauses), _date(a)
    except DataError as exc:
        print(f"Erro nos dados: {exc}", file=sys.stderr)
        return 2
    result = analyze(ds, today)
    found = next((r for r in result["results"] if r["vendor"].id == norm(a.id)), None)
    if not found:
        print("Fornecedor não encontrado.", file=sys.stderr)
        return 2
    print(report.vendor_text(found, today))
    return 0


def cmd_request(a) -> int:
    try:
        ds = load_dataset(a.vendors)
    except DataError as exc:
        print(f"Erro nos dados: {exc}", file=sys.stderr)
        return 2
    os.makedirs(a.out, exist_ok=True)
    files = rq.build(ds, a.only, not a.no_bcb)
    for name, text in files.items():
        with open(os.path.join(a.out, name), "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
        print("criado:", os.path.join(a.out, name))
    print("\nEnvie os 'questionario_*.csv' aos fornecedores. Registre as respostas em respostas_modelo.csv e as cláusulas em clausulas_modelo.csv.")
    return 0


def cmd_questions(_a) -> int:
    for q in QUESTIONS:
        print(f"{q.id}  peso {q.weight}  [{q.domain}]  {q.text}")
    return 0


def cmd_clauses(_a) -> int:
    for c in CLAUSES:
        print(f"{c.id}  {'(só se supervisionada pelo BC) ' if c.bcb_only else ''}{c.text}")
    return 0


def cmd_rules(_a) -> int:
    for r in RULES:
        print(f"{r.id:<4} {r.severity:<9} {r.title}")
    return 0


def cmd_explain(a) -> int:
    r = next((x for x in RULES if x.id.lower() == a.id.lower()), None)
    if not r:
        print("Regra desconhecida. Veja 'rules'.", file=sys.stderr)
        return 2
    print(f"{r.id}: {r.title}\nSeveridade: {r.severity}   ComplianceMap: {', '.join(r.controls)}\n\nPor quê: {r.why}\nComo corrigir: {r.fix}")
    return 0


def cmd_samples(a) -> int:
    from .samples import write_samples
    for n in write_samples(a.dir):
        print("criado:", os.path.join(a.dir, n))
    return 0


def main(argv=None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    return {"assess": cmd_assess, "demo": cmd_demo, "show": cmd_show, "request": cmd_request, "questions": cmd_questions, "clauses": cmd_clauses,
            "rules": cmd_rules, "explain": cmd_explain, "samples": cmd_samples}[a.cmd](a)
