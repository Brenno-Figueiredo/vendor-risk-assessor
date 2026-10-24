import contextlib
import csv
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vendorrisk import report, requests as rq  # noqa: E402
from vendorrisk.cli import main  # noqa: E402
from vendorrisk.engine import analyze, relevant_service  # noqa: E402
from vendorrisk.io import DataError, load_dataset, load_vendors, read_rows  # noqa: E402
from vendorrisk.model import Answer, ClauseRecord, Dataset, Vendor, norm, parse_date  # noqa: E402
from vendorrisk.questions import BY_ID, CLAUSES, QUESTIONS  # noqa: E402
from vendorrisk.samples import REF, write_samples  # noqa: E402
from vendorrisk.scoring import assess_controls, evidence_ok, inherent, level_of, residual_risk, scope  # noqa: E402
from vendorrisk.validators import make_cnpj, valid_cnpj  # noqa: E402

TODAY = date(2026, 10, 22)
RECENT = date(2026, 6, 1)


def V(**kw):
    base = dict(id="v1", nome="Fornecedor Teste", cnpj=make_cnpj("20000001") if False else make_cnpj("200000010001"), servico="Serviço", categoria="outros",
                criticidade="media", dados="nenhum", volume="baixo", acesso="nenhum", exterior=False, paises="", subcontrata=False, nuvem=False,
                contrato_inicio=date(2024, 1, 1), contrato_fim=date(2028, 1, 1), responsavel="Responsável", ultima_avaliacao=date(2026, 6, 1), incidentes_12m=0)
    base.update(kw)
    return Vendor(**base)


def CRIT(**kw):
    """Perfil de risco crítico (14 pontos de risco inerente)."""
    return V(criticidade="alta", dados="sensiveis", volume="alto", acesso="privilegiado", exterior=True, paises="EUA", subcontrata=True, nuvem=True, **kw)


def A(q, resp="sim", ev=True, vid="v1", when=RECENT):
    return Answer(vid, q, resp, "Evidência" if ev else "", when if ev else None)


def full_yes(vendor):
    return [A(q.id, vid=vendor.id) for q in scope(vendor, inherent(vendor)["tier"])]


def D(vendor, answers=(), clauses=None, others=()):
    vendors = {v.id: v for v in (vendor, *others)}
    return Dataset(vendors, list(answers), clauses)


def run(ds, **cfg):
    return analyze(ds, TODAY, cfg)


def finds(result, rule, vid=None):
    return [f for f in result["findings"] if f.rule == rule and (vid is None or f.vendor == vid)]


class ValidatorsAndModelTests(unittest.TestCase):
    def test_cnpj(self):
        self.assertTrue(valid_cnpj("11.222.333/0001-81"))
        self.assertFalse(valid_cnpj("11.222.333/0001-99"))
        self.assertFalse(valid_cnpj("00.000.000/0000-00"))
        self.assertTrue(valid_cnpj(make_cnpj("12ABC34501DE")))

    def test_norm_and_dates(self):
        self.assertEqual(norm("  Não   Atende "), "nao atende")
        self.assertEqual(parse_date("22/10/2026"), TODAY)
        self.assertIsNone(parse_date("amanhã"))

    def test_question_bank_is_consistent(self):
        self.assertEqual(len({q.id for q in QUESTIONS}), len(QUESTIONS))
        for q in QUESTIONS:
            self.assertIn(q.weight, (1, 2, 3))
            self.assertGreater(len(q.text), 30)
            self.assertGreater(len(q.evidence), 8)
        self.assertEqual(len({c.id for c in CLAUSES}), len(CLAUSES))

    def test_clauses_follow_the_art_17_structure(self):
        self.assertEqual(sum(1 for c in CLAUSES if c.bcb_only), 4)
        self.assertTrue(all(c.short for c in CLAUSES))


class IOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, name, data: bytes):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_bom_semicolon_and_cp1252(self):
        v = load_vendors(self.write("a.csv", "\ufeffid;nome;serviço\nf1;Café Ltda;Cantina\n".encode("utf-8")))
        self.assertEqual((v["f1"].nome, v["f1"].servico), ("Café Ltda", "Cantina"))
        v = load_vendors(self.write("b.csv", "id;nome\nf1;Conceição Ltda\n".encode("cp1252")))
        self.assertEqual(v["f1"].nome, "Conceição Ltda")

    def test_quoted_field_with_the_delimiter_inside(self):
        """Bug real dos exemplos: a lista de países tinha ';' e deslocava todas as colunas."""
        v = load_vendors(self.write("c.csv", b'id;nome;paises;responsavel\nf1;Nuvem;"EUA; Irlanda";Equipe de TI\n'))
        self.assertEqual((v["f1"].paises, v["f1"].responsavel), ("EUA; Irlanda", "Equipe de TI"))

    def test_aliases_and_value_normalization(self):
        v = load_vendors(self.write("d.csv", "Fornecedor;Razão Social;Dados Pessoais;Acesso aos sistemas;Criticidade;Nuvem\nx;Empresa;sim;admin;crítica;S\n".encode("utf-8")))["x"]
        self.assertEqual((v.dados, v.acesso, v.criticidade, v.nuvem), ("comuns", "privilegiado", "alta", True))
        v = load_vendors(self.write("e.csv", b"id;nome;dados;volume\ny;Outra;sensivel;alta\n"))["y"]
        self.assertEqual((v.dados, v.volume), ("sensiveis", "alto"))

    def test_missing_columns_and_empty_and_missing_file(self):
        with self.assertRaises(DataError) as ctx:
            read_rows(self.write("f.csv", b"nome;cnpj\nx;y\n"), ["id"], "fornecedores", ["id", "nome"])
        self.assertIn("faltam", str(ctx.exception))
        with self.assertRaises(DataError):
            load_vendors(self.write("g.csv", b""))
        with self.assertRaises(DataError):
            load_vendors("/nao/existe.csv")

    def test_answers_clauses_and_unknown_vendors(self):
        vp = self.write("v.csv", b"id;nome\nf1;A\n")
        ap = self.write("r.csv", b"fornecedor;pergunta;resposta;evidencia;data_evidencia\nF1;q04;Sim;doc;01/06/2026\nghost;Q04;sim;;\n")
        cp = self.write("c.csv", b"fornecedor;clausula;presente\nf1;c01;Parcial\n")
        ds = load_dataset(vp, ap, cp)
        self.assertEqual((ds.answers[0].vendor, ds.answers[0].question, ds.answers[0].resposta, ds.answers[0].data_evidencia), ("f1", "Q04", "sim", RECENT))
        self.assertEqual((ds.clauses[0].clause, ds.clauses[0].presente), ("C01", "parcial"))
        self.assertTrue(any("1 fornecedor" in n for n in ds.notes))


class ScoringTests(unittest.TestCase):
    def test_inherent_points_and_tiers(self):
        self.assertEqual(inherent(CRIT())["points"], 14)
        self.assertEqual(inherent(CRIT())["tier"], "critico")
        self.assertEqual(inherent(V(criticidade="baixa"))["tier"], "baixo")
        self.assertEqual(inherent(V())["tier"], "baixo")                                          # média, sem dados e sem acesso: 2 pontos
        self.assertEqual(inherent(V(criticidade="alta", dados="comuns", acesso="leitura"))["tier"], "medio")   # 3+2+1 = 6
        self.assertEqual(inherent(V(criticidade="alta", dados="comuns", volume="alto", acesso="leitura"))["tier"], "alto")   # 7
        self.assertEqual(inherent(V(incidentes_12m=3))["points"], 4)                               # 2 + 2
        self.assertEqual(inherent(V(incidentes_12m=1))["points"], 3)

    def test_scope_by_tier_and_profile(self):
        always_only = {q.id for q in scope(V(criticidade="baixa"), "baixo")}
        self.assertTrue(all(BY_ID[i].weight == 3 for i in always_only))
        self.assertNotIn("Q23", always_only)                                                       # exterior/nuvem não se aplica
        crit = {q.id for q in scope(CRIT(), "critico")}
        for needed in ("Q07", "Q20", "Q23", "Q24", "Q27"):
            self.assertIn(needed, crit)
        self.assertGreater(len(crit), len(always_only))

    def test_evidence_validity(self):
        ok = A("Q01")
        self.assertTrue(evidence_ok(ok, TODAY, 365))
        self.assertFalse(evidence_ok(A("Q01", when=date(2025, 1, 1)), TODAY, 365))              # vencida
        self.assertFalse(evidence_ok(A("Q01", when=date(2027, 1, 1)), TODAY, 365))              # data no futuro
        self.assertFalse(evidence_ok(A("Q01", ev=False), TODAY, 365))
        self.assertFalse(evidence_ok(Answer("v1", "Q01", "sim", "doc", None), TODAY, 365))      # sem data
        self.assertFalse(evidence_ok(None, TODAY, 365))

    def test_credit_rules_no_evidence_no_full_credit(self):
        v = V(criticidade="baixa")
        qs = {q.id: q for q in scope(v, "baixo")}
        qid = next(iter(qs))
        for answer, expected in ((A(qid), 1.0), (A(qid, ev=False), 0.5), (A(qid, "parcial"), 0.5), (A(qid, "parcial", ev=False), 0.25), (A(qid, "nao", ev=False), 0.0)):
            row = next(r for r in assess_controls(v, "baixo", {qid: answer}, TODAY)["rows"] if r["q"].id == qid)
            self.assertEqual(row["credit"], expected, answer.resposta)

    def test_not_applicable_needs_a_justification(self):
        v = V(criticidade="baixa")
        qid = next(iter(q.id for q in scope(v, "baixo")))
        justified = assess_controls(v, "baixo", {qid: Answer("v1", qid, "na", "não usamos nuvem", None)}, TODAY)
        row = next(r for r in justified["rows"] if r["q"].id == qid)
        self.assertEqual((row["status"], row["credit"]), ("na", None))
        bare = assess_controls(v, "baixo", {qid: Answer("v1", qid, "na", "", None)}, TODAY)
        row = next(r for r in bare["rows"] if r["q"].id == qid)
        self.assertEqual((row["status"], row["credit"]), ("na_sem_justificativa", 0.0))

    def test_effectiveness_is_weighted(self):
        v = V(criticidade="baixa")
        result = assess_controls(v, "baixo", {q.id: A(q.id) for q in scope(v, "baixo")}, TODAY)
        self.assertEqual(result["effectiveness"], 1.0)
        none = assess_controls(v, "baixo", {}, TODAY)
        self.assertEqual((none["effectiveness"], none["answered"]), (0.0, 0))

    def test_residual_has_a_floor_and_levels(self):
        self.assertEqual(residual_risk(80, 1.0), 8)                  # controles perfeitos não zeram o risco
        self.assertEqual(residual_risk(80, 0.0), 80)                 # sem controles, residual = inerente
        self.assertEqual(residual_risk(50, 0.5), 28)
        self.assertIsNone(residual_risk(50, None))
        self.assertEqual([level_of(x) for x in (0, 17, 18, 35, 55, 100)], ["baixo", "baixo", "medio", "alto", "critico", "critico"])


class RuleTests(unittest.TestCase):
    def test_v01_contract(self):
        sev = lambda **kw: [(f.severity, f.detail) for f in finds(run(D(V(**kw))), "V01")]   # noqa: E731
        self.assertEqual(sev(contrato_fim=date(2028, 1, 1)), [])
        self.assertEqual(sev(contrato_fim=date(2026, 12, 1))[0][0], "medium")                   # vence em 40 dias
        self.assertEqual(sev(contrato_fim=date(2026, 9, 30))[0][0], "medium")                   # vencido, mas fornecedor de nível baixo
        self.assertEqual(sev(contrato_fim=date(2026, 9, 30), criticidade="alta", dados="comuns", acesso="leitura")[0][0], "high")   # nível médio ou maior
        self.assertEqual(sev(contrato_fim=None)[0][0], "low")
        self.assertEqual(len(finds(run(D(V(contrato_fim=date(2027, 1, 15))), expiry_days=400), "V01")), 1)

    def test_v02_v03_assessment_dates(self):
        old = V(ultima_avaliacao=date(2025, 1, 1), criticidade="alta", dados="sensiveis", acesso="privilegiado", volume="alto")     # crítico: ciclo de 1 ano
        self.assertEqual(finds(run(D(old)), "V02")[0].severity, "high")
        self.assertEqual(finds(run(D(V(ultima_avaliacao=date(2025, 1, 1)))), "V02"), [])           # nível baixo: ciclo de 3 anos
        never = run(D(V(ultima_avaliacao=None, criticidade="alta", dados="comuns", acesso="leitura", volume="alto")))
        self.assertEqual(finds(never, "V03")[0].severity, "high")
        self.assertEqual(finds(run(D(V(ultima_avaliacao=None, criticidade="baixa"))), "V03")[0].severity, "medium")
        with_answers = run(D(V(ultima_avaliacao=None), [A("Q02")]))
        self.assertEqual(finds(with_answers, "V03")[0].severity, "low")

    def test_v04_incomplete_questionnaire(self):
        v = CRIT()
        qs = scope(v, "critico")
        half = run(D(v, [A(q.id) for q in qs[: len(qs) // 3]]))
        self.assertEqual(finds(half, "V04")[0].severity, "high")                                # menos de 50% em fornecedor crítico
        most = run(D(v, [A(q.id) for q in qs[: int(len(qs) * 0.6)]]))
        self.assertEqual(finds(most, "V04")[0].severity, "medium")
        self.assertEqual(finds(run(D(v, full_yes(v))), "V04"), [])

    def test_v05_yes_without_evidence(self):
        v = V(criticidade="baixa")
        ans = [A(q.id, ev=False) for q in scope(v, "baixo")]
        got = finds(run(D(v, ans)), "V05")
        self.assertEqual(len(got), 1)
        self.assertIn("sem evidência", got[0].detail)
        self.assertEqual(finds(run(D(v, [A(q.id, when=date(2020, 1, 1)) for q in scope(v, "baixo")])), "V05")[0].rule, "V05")   # evidência vencida

    def test_v06_essential_control_missing_and_control_mapping(self):
        v = V(dados="comuns")
        ans = full_yes(v)
        ans = [a for a in ans if a.question not in ("Q13", "Q22", "Q04")] + [A("Q13", "nao", False), A("Q22", "nao", False), A("Q04", "nao", False)]
        got = {f.detail.split(" ")[0]: f for f in finds(run(D(v, ans)), "V06")}
        self.assertEqual(set(got), {"Q04", "Q13", "Q22"})
        self.assertIn("TER-04", got["Q13"].controls)
        self.assertIn("TER-02", got["Q22"].controls)
        self.assertEqual(got["Q04"].controls, ["TER-01"])

    def test_v06_skips_questions_with_dedicated_rules(self):
        v = CRIT()
        ans = [a for a in full_yes(v) if a.question != "Q07"] + [A("Q07", "nao", False)]
        self.assertEqual([f for f in finds(run(D(v, ans)), "V06") if f.detail.startswith("Q07")], [])
        self.assertEqual(finds(run(D(v, ans)), "V11")[0].severity, "critical")

    def test_v07_contract_clauses(self):
        v = CRIT()
        self.assertEqual(finds(run(D(v, clauses=None)), "V07"), [])                              # sem planilha: regra pulada
        self.assertEqual(finds(run(D(v, clauses=[ClauseRecord("v1", "C12", "sim")], others=())), "V07")[0].severity, "high")
        none = run(D(v, clauses=[ClauseRecord("other", "C01", "sim")]))
        self.assertEqual(finds(none, "V07")[0].severity, "medium")                               # contrato não analisado
        self.assertIn("não analisado", finds(none, "V07")[0].detail)
        every = [ClauseRecord("v1", c.id, "sim") for c in CLAUSES]
        self.assertEqual(finds(run(D(v, clauses=every)), "V07"), [])
        partial = [ClauseRecord("v1", c.id, "parcial" if c.id == "C02" else "sim") for c in CLAUSES]
        self.assertIn("C02", finds(run(D(v, clauses=partial)), "V07")[0].detail)

    def test_v07_regulated_flag_and_tier(self):
        only_bcb = [ClauseRecord("v1", c.id, "nao" if c.bcb_only else "sim") for c in CLAUSES]
        self.assertEqual(len(finds(run(D(CRIT(), clauses=only_bcb)), "V07")), 1)                 # supervisionada: faltam C07, C08, C10, C11
        self.assertEqual(finds(run(D(CRIT(), clauses=only_bcb), regulado_bcb=False), "V07"), [])  # não supervisionada: dispensadas
        medio = V(criticidade="alta", dados="comuns", acesso="leitura")
        got = finds(run(D(medio, clauses=[ClauseRecord("v1", "C12", "nao")])), "V07")
        self.assertEqual((got[0].severity, "C12" in got[0].detail), ("medium", True))            # nível médio só exige o DPA

    def test_v08_data_abroad(self):
        v = V(dados="comuns", exterior=True, paises="Irlanda")
        bad = finds(run(D(v, [A("Q24", "nao", False)], clauses=[ClauseRecord("v1", "C01", "nao")])), "V08")
        self.assertEqual(len(bad), 1)
        self.assertIn("Irlanda", bad[0].detail)
        good = D(v, [A("Q24"), A("Q23")], clauses=[ClauseRecord("v1", c.id, "sim") for c in CLAUSES])
        self.assertEqual(finds(run(good), "V08"), [])
        self.assertEqual(finds(run(D(V(dados="comuns"))), "V08"), [])                            # sem dados no exterior

    def test_v09_subcontracting(self):
        v = V(subcontrata=True)
        self.assertEqual(finds(run(D(v, [A("Q20", "nao", False)])), "V09")[0].severity, "medium")
        crit = CRIT()
        ans = [a for a in full_yes(crit) if a.question != "Q20"] + [A("Q20", "nao", False)]
        self.assertEqual(finds(run(D(crit, ans)), "V09")[0].severity, "high")
        self.assertEqual(finds(run(D(V(subcontrata=False))), "V09"), [])

    def test_v10_audit_rights_only_for_critical_and_high(self):
        crit = CRIT()
        ans = [a for a in full_yes(crit) if a.question != "Q30"] + [A("Q30", "nao", False)]
        self.assertEqual(len(finds(run(D(crit, ans)), "V10")), 1)
        self.assertEqual(finds(run(D(V(criticidade="baixa"), [A("Q30", "nao", False)])), "V10"), [])

    def test_v11_privileged_access(self):
        v = V(acesso="privilegiado")
        self.assertEqual(finds(run(D(v, [A("Q07", "nao", False)])), "V11")[0].severity, "critical")
        self.assertEqual(finds(run(D(v, [A("Q07", ev=False)])), "V11")[0].severity, "high")
        self.assertEqual(finds(run(D(v, [A("Q07")])), "V11"), [])
        self.assertEqual(finds(run(D(V(acesso="leitura"))), "V11"), [])

    def test_v12_to_v16_registry_rules(self):
        self.assertEqual(finds(run(D(V(incidentes_12m=1))), "V12")[0].severity, "medium")
        self.assertEqual(finds(run(D(V(incidentes_12m=3))), "V12")[0].severity, "high")
        self.assertEqual(finds(run(D(V(responsavel=""))), "V13")[0].severity, "low")
        self.assertEqual(finds(run(D(CRIT(responsavel=""))), "V13")[0].severity, "medium")
        self.assertEqual(finds(run(D(V(cnpj="11.222.333/0001-99"))), "V14")[0].severity, "medium")
        self.assertEqual(finds(run(D(V(cnpj=""))), "V14")[0].severity, "low")
        a, b = V(id="a"), V(id="b")
        self.assertEqual({f.vendor for f in finds(run(D(a, others=(b,))), "V15")}, {"a", "b"})
        v = V(criticidade="baixa")
        ans = [Answer("v1", q.id, "na", "", None) for q in scope(v, "baixo")]
        self.assertEqual(len(finds(run(D(v, ans)), "V16")), 1)


class EngineTests(unittest.TestCase):
    def test_critical_finding_raises_the_level(self):
        v = V(acesso="privilegiado")
        result = run(D(v, [A("Q07", "nao", False)] + [A(q.id) for q in scope(v, inherent(v)["tier"]) if q.id != "Q07"]))
        r = result["results"][0]
        self.assertLess(r["residual"], 18)                    # o número, sozinho, diria "baixo"
        self.assertEqual(r["level"], "alto")                  # mas o achado crítico mantém o nível alto

    def test_plan_is_sorted_with_due_dates_by_severity(self):
        v = CRIT(ultima_avaliacao=None, responsavel="Ana")
        plan = run(D(v))["plan"]
        self.assertEqual(plan[0]["severity"], "high" if not any(p["severity"] == "critical" for p in plan) else "critical")
        for p in plan:
            self.assertEqual((p["due"] - TODAY).days, {"critical": 30, "high": 60, "medium": 90, "low": 180}[p["severity"]])
            self.assertEqual(p["owner"], "Ana")
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        self.assertEqual([order[p["severity"]] for p in plan], sorted(order[p["severity"]] for p in plan))

    def test_ranking_and_summary(self):
        safe = V(id="a", nome="Seguro", criticidade="baixa")
        risky = CRIT(id="b", nome="Arriscado", ultima_avaliacao=None)
        result = run(D(safe, full_yes(safe), others=(risky,)))
        self.assertEqual([r["vendor"].id for r in result["results"]], ["b", "a"])
        s = result["summary"]
        self.assertEqual((s["vendors"], s["never_assessed"], s["relevant"]), (2, 1, 1))
        self.assertEqual(sum(s["by_tier"].values()), 2)

    def test_relevant_service_and_next_review(self):
        self.assertTrue(relevant_service(V(nuvem=True), "alto"))
        self.assertTrue(relevant_service(V(categoria="processamento"), "critico"))
        self.assertFalse(relevant_service(V(nuvem=True), "medio"))
        self.assertFalse(relevant_service(V(categoria="outros"), "critico"))
        r = run(D(V(ultima_avaliacao=date(2026, 1, 1), criticidade="alta", dados="comuns", acesso="leitura", volume="alto")))["results"][0]
        self.assertEqual((r["tier"], r["next_review"]), ("alto", date(2027, 1, 1)))

    def test_missing_clauses_are_reported_as_skipped(self):
        result = run(D(V()))
        self.assertEqual([s["rule"] for s in result["skipped"]], ["V07"])
        self.assertEqual(run(D(V(), clauses=[]))["skipped"], [])


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        write_samples(self.tmp)
        p = lambda n: os.path.join(self.tmp, n)  # noqa: E731
        self.ds = load_dataset(p("fornecedores.csv"), p("respostas.csv"), p("clausulas.csv"))
        self.result = analyze(self.ds, date.fromisoformat(REF))

    def test_html_and_scorecard_escape_names(self):
        self.ds.vendors["f01"].nome = "<script>alert(1)</script>"
        self.ds.vendors["f01"].servico = "<img src=x onerror=alert(1)>"
        result = analyze(self.ds, date.fromisoformat(REF))
        doc = report.render_html(result)
        self.assertNotIn("<script>alert", doc)
        self.assertNotIn("<img src=x", doc)
        card = report.render_scorecard(next(r for r in result["results"] if r["vendor"].id == "f01"), TODAY)
        self.assertNotIn("<script>alert", card)

    def test_csv_neutralizes_formulas_and_keeps_empty_cells_empty(self):
        """Regressão do bug do apóstrofo: célula vazia deve continuar vazia."""
        self.ds.vendors["f01"].nome = "=HYPERLINK(\"http://x\")"
        result = analyze(self.ds, date.fromisoformat(REF))
        rows = list(csv.reader(io.StringIO(report.findings_csv(result)), delimiter=";"))
        self.assertIn("'=HYPERLINK(\"http://x\")", [r[1] for r in rows])
        plan = list(csv.reader(io.StringIO(report.plan_csv(result)), delimiter=";"))
        self.assertTrue(all(r[-1] == "" and r[-2] == "" for r in plan[1:]))                   # colunas de acompanhamento em branco
        self.assertTrue(all(c != "'" for r in rows + plan for c in r))

    def test_csv_guard_function_never_touches_empty_values(self):
        """Regressão direta do bug do apóstrofo: '' in '=+-@' é True em Python, então um teste por 'in' prefixava células vazias."""
        self.assertEqual(report._safe(""), "")
        self.assertIsNone(report._safe(None))
        self.assertEqual(report._safe("texto"), "texto")
        for dangerous in ("=1+1", "+1", "-1", "@SUM(A1)", "\tcmd", "\rcmd"):
            self.assertEqual(report._safe(dangerous), "'" + dangerous)

    def test_exports_to_other_tools_are_aggregated_without_names(self):
        cm = report.to_compliancemap(self.result, True)
        feed = json.dumps(report.to_feed(self.result), ensure_ascii=False)
        for secret in ("Callcenter", "Nuvem Exemplo", "Cobranca", "f03"):
            self.assertNotIn(secret, cm)
            self.assertNotIn(secret, feed)
        self.assertIn("Callcenter", report.to_json(self.result))                                # o relatório local completo tem

    def test_compliancemap_format_and_unknowns(self):
        data = json.loads(report.to_compliancemap(self.result, True))
        status = {r["control"]: r["status"] for r in data["results"]}
        self.assertEqual(set(status), {"TER-01", "TER-02", "TER-03", "TER-04", "ACC-04"})
        self.assertEqual(status["TER-01"], "fail")
        self.assertEqual(status["TER-04"], "fail")
        for row in data["results"]:
            self.assertEqual(set(row), {"check", "control", "status", "detail", "platform"})
        self.assertEqual({r["control"]: r["status"] for r in json.loads(report.to_compliancemap(self.result, False))["results"]}["TER-02"], "unknown")
        clean = V(criticidade="baixa")
        only = analyze(D(clean, full_yes(clean)), TODAY)
        st = {r["control"]: r["status"] for r in json.loads(report.to_compliancemap(only, False))["results"]}
        self.assertEqual((st["TER-03"], st["ACC-04"]), ("unknown", "unknown"))                  # sem nuvem e sem acesso privilegiado

    def test_feed_is_one_event_per_rule(self):
        events = report.to_feed(self.result)
        self.assertEqual(len(events), len(self.result["summary"]["by_rule"]))
        self.assertTrue(all((e["source"], e["type"]) == ("vendorrisk", "generic") for e in events))

    def test_text_outputs(self):
        text = report.render_text(self.result)
        for expected in ("AVALIAÇÃO DE RISCO", "Ações mais urgentes", "s/ resp.", "decisão sobre contratar"):
            self.assertIn(expected, text)
        card = report.vendor_text(next(r for r in self.result["results"] if r["vendor"].id == "f03"), TODAY)
        self.assertIn("Reavaliação VENCIDA", card)
        self.assertIn("Por que este nível", card)


class RequestTests(unittest.TestCase):
    def test_questionnaire_is_scoped_to_the_vendor(self):
        ds = Dataset({"a": V(id="a", criticidade="baixa"), "b": CRIT(id="b")})
        files = rq.build(ds)
        qa = list(csv.reader(io.StringIO(files["questionario_a.csv"]), delimiter=";"))
        qb = list(csv.reader(io.StringIO(files["questionario_b.csv"]), delimiter=";"))
        self.assertLess(len(qa), len(qb))
        self.assertTrue(all(r[3] == "3" for r in qa[1:]))                                       # baixo risco: só as perguntas essenciais
        cons = list(csv.reader(io.StringIO(files["respostas_modelo.csv"]), delimiter=";"))
        self.assertEqual(cons[0], ["fornecedor", "pergunta", "resposta", "evidencia", "data_evidencia"])
        self.assertEqual(len(cons) - 1, (len(qa) - 1) + (len(qb) - 1))
        cl = list(csv.reader(io.StringIO(files["clausulas_modelo.csv"]), delimiter=";"))
        self.assertGreater(len([r for r in cl if r[0] == "b"]), len([r for r in cl if r[0] == "a"]))

    def test_only_one_vendor_and_safe_file_names(self):
        ds = Dataset({"a": V(id="a"), "../../etc/x": V(id="../../etc/x")})
        files = rq.build(ds, only="a")
        self.assertIn("questionario_a.csv", files)
        self.assertFalse(any("etc" in n for n in files if n.startswith("questionario")))
        self.assertTrue(all("/" not in n and ".." not in n for n in rq.build(ds)))
        self.assertEqual(rq.slug("../../etc/x"), "etc-x")

    def test_no_bcb_drops_bcb_only_clauses(self):
        ds = Dataset({"b": CRIT(id="b")})
        with_bcb = rq.build(ds, bcb=True)["clausulas_modelo.csv"]
        without = rq.build(ds, bcb=False)["clausulas_modelo.csv"]
        self.assertIn("C07", with_bcb)
        self.assertNotIn("C07", without)


class SampleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        write_samples(self.tmp)
        p = lambda n: os.path.join(self.tmp, n)  # noqa: E731
        self.ds = load_dataset(p("fornecedores.csv"), p("respostas.csv"), p("clausulas.csv"))
        self.result = analyze(self.ds, date.fromisoformat(REF))

    def test_columns_survive_the_semicolon_inside_the_countries_field(self):
        v = self.ds.vendors["f01"]
        self.assertEqual((v.paises, v.responsavel, v.contrato_fim), ("Estados Unidos; Irlanda", "Equipe de TI", date(2027, 1, 31)))

    def test_every_planted_problem_is_found(self):
        found = {(f.rule, f.vendor) for f in self.result["findings"]}
        planted = {("V01", "f05"), ("V01", "f08"), ("V02", "f03"), ("V03", "f02"), ("V04", "f05"), ("V05", "f03"), ("V06", "f03"), ("V07", "f03"),
                   ("V07", "f07"), ("V08", "f08"), ("V09", "f03"), ("V10", "f03"), ("V11", "f03"), ("V12", "f10"), ("V13", "f05"), ("V14", "f10"),
                   ("V15", "f06"), ("V15", "f11"), ("V16", "f10")}
        self.assertTrue(planted <= found, planted - found)

    def test_good_vendors_have_little_risk(self):
        by = {r["vendor"].id: r for r in self.result["results"]}
        for vid in ("f01", "f04", "f06"):
            self.assertEqual(by[vid]["level"], "baixo", vid)
        self.assertEqual(by["f03"]["level"], "alto")
        self.assertEqual(self.result["results"][0]["vendor"].id, "f02")                         # nunca avaliado: residual igual ao inerente

    def test_summary_numbers(self):
        s = self.result["summary"]
        self.assertEqual((s["vendors"], s["never_assessed"], s["overdue"]), (11, 3, 4))
        self.assertGreaterEqual(s["relevant"], 4)


class CLITests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_demo_with_all_outputs(self):
        with tempfile.TemporaryDirectory() as d:
            outs = {k: os.path.join(d, "o." + k) for k in ("json", "csv", "plan", "html", "cm")}
            feed, cards = os.path.join(d, "f.jsonl"), os.path.join(d, "fichas")
            code, out, err = self.run_cli("demo", "--dir", os.path.join(d, "s"), "--no-color", "--json", outs["json"], "--csv", outs["csv"],
                                          "--plan", outs["plan"], "--html", outs["html"], "--compliancemap", outs["cm"], "--feed", feed, "--scorecards", cards)
            self.assertEqual((code, err), (0, ""))
            for p in list(outs.values()) + [feed]:
                self.assertGreater(os.path.getsize(p), 40, p)
            self.assertEqual(len(os.listdir(cards)), 11)
            self.assertIn("FICTÍCIOS", out)

    def test_fail_on_and_no_bcb(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.run_cli("demo", "--dir", d, "--no-color", "--fail-on", "critical")[0], 1)
            self.assertIn("sem Banco Central", self.run_cli("demo", "--dir", d, "--no-color", "--no-bcb")[1])

    def test_assess_with_files_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            write_samples(d)
            p = lambda n: os.path.join(d, n)  # noqa: E731
            code, out, _ = self.run_cli("assess", "--vendors", p("fornecedores.csv"), "--today", REF, "--no-color")
            self.assertEqual(code, 0)
            self.assertIn("V07: faltam dados", out)                                          # sem cláusulas: regra pulada e dito
            self.assertEqual(self.run_cli("assess", "--vendors", "/nao/existe.csv")[0], 2)
            self.assertEqual(self.run_cli("assess", "--vendors", p("fornecedores.csv"), "--today", "ontem")[0], 2)

    def test_show_request_and_lists(self):
        code, out, _ = self.run_cli("show", "f03", "--demo")
        self.assertEqual(code, 0)
        self.assertIn("Callcenter Modelo", out)
        self.assertEqual(self.run_cli("show", "zzz", "--demo")[0], 2)
        self.assertEqual(self.run_cli("show", "f03")[0], 2)
        self.assertIn("Q01", self.run_cli("questions")[1])
        self.assertIn("C01", self.run_cli("clauses")[1])
        self.assertIn("V11", self.run_cli("rules")[1])
        self.assertIn("Por quê", self.run_cli("explain", "v11")[1])
        self.assertEqual(self.run_cli("explain", "V99")[0], 2)
        with tempfile.TemporaryDirectory() as d:
            write_samples(d)
            out_dir = os.path.join(d, "pedidos")
            self.assertEqual(self.run_cli("request", "--vendors", os.path.join(d, "fornecedores.csv"), "--out", out_dir)[0], 0)
            self.assertIn("respostas_modelo.csv", os.listdir(out_dir))
            self.assertEqual(len([f for f in os.listdir(out_dir) if f.startswith("questionario_")]), 11)


if __name__ == "__main__":
    unittest.main()
