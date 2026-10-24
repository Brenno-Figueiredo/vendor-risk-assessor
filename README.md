# VendorRisk

Avaliação de **risco de fornecedores (gestão de riscos de terceiros, TPRM)** em Python, **sem dependências externas**. Para cada
fornecedor ela calcula o **nível de risco**, confere os **controles com evidências** e as **cláusulas do contrato**, e entrega um
**plano de ação com prazo e responsável**.

```
python app.py demo --html relatorio.html --plan plano.csv --scorecards fichas     # fornecedores FICTÍCIOS
python app.py request --vendors fornecedores.csv                                  # questionários para enviar aos fornecedores
```

## Por que isso importa

Fornecedor que acessa seus dados ou sistemas é **parte do seu risco**: o incidente dele é incidente seu. Em instituições
reguladas, isso é obrigação: a **Res. CMN 4.893** trata a contratação de serviços de processamento, armazenamento e nuvem nos
arts. 11 a 18 (diligência **documentada antes de contratar** no art. 12 e **cláusulas obrigatórias** no art. 17). A **LGPD** responsabiliza
quem contrata (art. 42) e exige que o operador trate os dados só sob instrução (art. 39). A **ISO 27001** cobre fornecedores em
`A.5.19` a `A.5.23`.

> **Fonte e limites.** A lista de cláusulas do art. 17 segue o resumo de um escritório de advocacia (Baker McKenzie, *Cloud
> Compliance Center*): é **fonte secundária**, então **confirme no texto oficial** do Banco Central. A definição de **"serviço
> relevante"** é da instituição e do jurídico; a ferramenta só marca os **prováveis** (★). **Não é parecer jurídico.**

## Como o risco é calculado

**1. Risco inerente** (o quanto o fornecedor *pode* nos prejudicar, antes de olhar os controles dele):

| Fator | Pontos |
|---|---|
| criticidade do serviço (alta / média / baixa) | 3 / 2 / 1 |
| dados pessoais (sensíveis / comuns) e volume alto | 3 / 2, mais 1 |
| acesso aos nossos sistemas (privilegiado / leitura) | 3 / 1 |
| dados fora do Brasil · subcontratação · nuvem | 2 · 1 · 1 |
| incidentes nos últimos 12 meses (1 ou 2 / 3 ou mais) | 1 / 2 |

Pontos → **nível**: **crítico** (10 ou mais), **alto** (7 a 9), **médio** (4 a 6), **baixo** (menos de 4).
O nível define **quantas perguntas** o fornecedor recebe (os de baixo risco respondem só o essencial), **a validade das evidências**
e a **frequência da reavaliação** (crítico e alto: 12 meses; médio: 24; baixo: 36).

**2. Eficácia dos controles**, com a regra central do projeto: **sem evidência válida, não há crédito completo.**

| Resposta | Crédito |
|---|---|
| "sim" com evidência (descrição e data dentro da validade) | 100% |
| "sim" sem evidência, ou com evidência vencida | 50% |
| "parcial" (com evidência / sem) | 50% / 25% |
| "não" ou sem resposta | 0% |
| "não se aplica" | só vale **com justificativa**; sem ela conta zero |

As perguntas têm peso 1, 2 ou 3, e a eficácia é a média ponderada.

**3. Risco residual** = inerente × (1 − eficácia × 0,9). O **piso de 10%** existe porque **nenhum fornecedor tem risco zero**.
Quem nunca respondeu fica com residual **igual ao inerente** (o que não foi avaliado não reduz risco). Níveis: crítico (55 ou mais),
alto (35), médio (18), baixo.

**4. Um achado crítico nunca fica escondido.** Se há um achado crítico (ex.: acesso privilegiado sem MFA), o nível sobe para
**pelo menos "alto"**, mesmo que a nota geral seja boa.

## Entradas (CSV)

| Arquivo | O que traz |
|---|---|
| **fornecedores.csv** | cadastro: id, nome, CNPJ, serviço, categoria, criticidade, dados pessoais, volume, acesso aos sistemas, exterior e países, subcontratação, nuvem, datas do contrato, responsável, última avaliação, incidentes |
| **respostas.csv** | fornecedor, pergunta, resposta (`sim`/`parcial`/`nao`/`na`), evidência, data da evidência |
| **clausulas.csv** | fornecedor, cláusula (C01 a C12), presente (`sim`/`parcial`/`nao`) |

Lê o CSV do **Excel brasileiro** (`;`, BOM, `cp1252`; campos com `;` entre aspas). O comando `request` já gera os questionários **só
com as perguntas do nível de cada fornecedor**, mais `respostas_modelo.csv` e `clausulas_modelo.csv` pré-preenchidos.

## O que ela verifica

**33 perguntas** (governança, acesso, dados, continuidade, incidentes, vulnerabilidades, subcontratados, privacidade, pessoas,
transparência, infraestrutura), cada uma com o que comprova a resposta. `python app.py questions`.
**12 cláusulas de contrato**, das quais 4 só valem para quem é supervisionado pelo Banco Central (`--no-bcb` as dispensa). `python app.py clauses`.

**16 regras**: contrato vencido ou perto de vencer (V01) · avaliação vencida (V02) · fornecedor nunca avaliado (V03) · questionário
incompleto (V04) · "sim" sem evidência (V05) · controle essencial não atendido (V06) · **cláusulas obrigatórias ausentes** (V07) ·
**dados no exterior sem salvaguardas** (V08) · subcontratação sem controle (V09) · sem direito de auditoria (V10) · **acesso
privilegiado sem controles** (V11) · incidentes recentes (V12) · sem responsável (V13) · CNPJ inválido (V14) · cadastro duplicado (V15) ·
"não se aplica" sem justificativa (V16). `python app.py explain V11`.

**Regra pulada não é regra aprovada:** sem a planilha de cláusulas, a V07 é pulada e **o relatório diz isso**; na exportação para o
ComplianceMap vira "não verificado".

## Saídas
Terminal · JSON · CSV de achados · **plano de ação** (prazo: crítico 30 dias, alto 60, médio 90, baixo 180; colunas de status em branco) ·
**painel HTML** · **ficha HTML por fornecedor** (`--scorecards`) · `show ID` (ficha no terminal).

## Integração com o resto da série
```bash
python app.py assess ... --compliancemap evidencias-auto.json --feed feed.jsonl
```
- **ComplianceMap:** `assess ... --auto evidencias-auto.json`. Controles de terceiros (TER-01 a TER-04 e ACC-04) declarados como
  "implementados" cuja evidência **falha** aqui são **rebaixados para "parcial"**.
- **Venator / CorrelAI:** um evento **por regra** (agregado).

## Confidencialidade
O relatório **descreve as fraquezas dos seus fornecedores** e pode citar contratos: **confidencial**. O `.gitignore` bloqueia
cadastros, respostas e relatórios reais (só os exemplos **fictícios** ficam no repositório). As exportações para outras
ferramentas são **agregadas, sem nomes**. Não use dados reais da sua empresa em demonstrações ou prints.

## Estrutura
```
app.py
vendorrisk/
  questions.py   33 perguntas e 12 cláusulas (redação própria)
  scoring.py     risco inerente, eficácia, risco residual
  rules.py       as 16 regras (achados e ações)
  engine.py      avaliação, ranking e plano de ação
  report.py      terminal, JSON, CSV, HTML, fichas, ComplianceMap e feed
  requests.py    questionários e planilhas de resposta
  io.py  validators.py  samples.py  cli.py
samples/         11 fornecedores FICTÍCIOS
tests/           52 testes automatizados
```

## Testes
```bash
python -m unittest discover -s tests -v
```
Cobrem a conta do risco (inclusive o piso e as faixas), cada regra, a leitura de CSV (inclusive campo com `;`), os questionários
por nível, as exportações sem dados de fornecedores e as proteções (HTML escapado e CSV sem injeção de fórmula).

## Limitações
- A pontuação é um **modelo**: os pesos e limites foram escolhidos pelo autor e devem ser **calibrados** à política da sua organização.
- Avalia o **que o fornecedor diz e comprova**. Não testa os controles dele nem faz varredura externa.
- As perguntas e cláusulas são **orientativas**; um jurídico deve revisar as cláusulas para o seu caso.
- Um achado é um **ponto de atenção**: a decisão de contratar, manter ou sair é **humana**.

## Ideias para evoluir
Histórico das avaliações (comparar a evolução do fornecedor), alerta de vencimento de contratos e certificados, avaliação contínua com
fontes externas, e questionários em formulário web.

## Projetos da série
[network-scanner](https://github.com/Brenno-Figueiredo/network-scanner) ·
[logwatch](https://github.com/Brenno-Figueiredo/logwatch) ·
[loginguard](https://github.com/Brenno-Figueiredo/loginguard) ·
[web-vuln-scanner](https://github.com/Brenno-Figueiredo/web-vuln-scanner) ·
[ssh-honeypot](https://github.com/Brenno-Figueiredo/ssh-honeypot) ·
[security-event-correlator](https://github.com/Brenno-Figueiredo/security-event-correlator) ·
[malware-static-analyzer](https://github.com/Brenno-Figueiredo/malware-static-analyzer) ·
[phishguard](https://github.com/Brenno-Figueiredo/phishguard) ·
[phishguard-ui](https://github.com/Brenno-Figueiredo/phishguard-ui) ·
[threat-intel-enricher](https://github.com/Brenno-Figueiredo/threat-intel-enricher) ·
[document-verifier](https://github.com/Brenno-Figueiredo/document-verifier) ·
[compliance-mapper](https://github.com/Brenno-Figueiredo/compliance-mapper) ·
[hardening-auditor](https://github.com/Brenno-Figueiredo/hardening-auditor) ·
[access-review-analyzer](https://github.com/Brenno-Figueiredo/access-review-analyzer)
