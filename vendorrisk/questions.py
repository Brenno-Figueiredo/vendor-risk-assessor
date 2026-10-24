"""Banco de perguntas e lista de cláusulas contratuais. Redação PRÓPRIA, escrita pelo autor.

As cláusulas seguem a estrutura do art. 17 da Res. CMN 4.893 segundo um resumo de escritório de advocacia (Baker McKenzie,
Cloud Compliance Center). É fonte SECUNDÁRIA: confirme no texto oficial do Banco Central.
As perguntas são orientativas: adapte-as à política de risco da sua organização."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Question:
    id: str
    domain: str
    text: str
    weight: int                       # 1 desejável, 2 importante, 3 essencial
    tags: Tuple[str, ...]             # "always" ou qualquer uma das condições do fornecedor
    evidence: str                     # o que comprova a resposta "sim"
    refs: Tuple[str, ...] = ()        # referências normativas (texto livre)

    def applies(self, vendor_tags: set) -> bool:
        return "always" in self.tags or bool(set(self.tags) & vendor_tags)


def Q(id, domain, text, weight, tags, evidence, refs=()):
    return Question(id, domain, text, weight, tuple(tags), evidence, tuple(refs))


QUESTIONS: List[Question] = [
    Q("Q01", "Governança", "O fornecedor tem política de segurança da informação aprovada e revisada no último ano?", 2, ["always"],
      "Política em PDF com data, versão e aprovação.", ["ISO A.5.1", "CMN art. 12"]),
    Q("Q02", "Governança", "Tem certificação ou relatório independente de segurança válido (ISO 27001, SOC 2 Tipo II ou equivalente)?", 3, ["always"],
      "Certificado ou relatório dentro da validade, com o escopo que cobre o nosso serviço.", ["ISO A.5.19", "ISO A.5.22", "CMN art. 12"]),
    Q("Q03", "Governança", "Há responsáveis designados por segurança e por privacidade (encarregado)?", 1, ["always"],
      "Nome e contato do responsável por segurança e do encarregado.", ["LGPD art. 41"]),
    Q("Q04", "Acesso", "O acesso administrativo e remoto aos sistemas que tratam os nossos dados exige MFA?", 3, ["always"],
      "Configuração de MFA ou política de acesso.", ["CMN art. 3º §2º I e §9º", "ISO A.8.5"]),
    Q("Q05", "Acesso", "Os acessos seguem o menor privilégio e são revisados ao menos a cada semestre?", 2, ["always"],
      "Relatório da última revisão de acessos.", ["ISO A.5.18", "CMN art. 3º §9º"]),
    Q("Q06", "Acesso", "As contas de quem sai da empresa são desativadas no mesmo dia?", 2, ["always"],
      "Procedimento de desligamento e amostra de registros.", ["ISO A.5.16"]),
    Q("Q07", "Acesso", "O acesso do fornecedor aos NOSSOS sistemas usa contas individuais, com MFA e registro de uso?", 3, ["acesso"],
      "Lista de contas e configuração de MFA e de logs.", ["CMN art. 3º §9º", "ISO A.5.15"]),
    Q("Q08", "Dados", "Os dados em trânsito são criptografados com protocolo atual (TLS)?", 3, ["dados", "nuvem"],
      "Configuração de TLS ou relatório de varredura.", ["CMN art. 3º §2º II", "LGPD art. 46", "ISO A.8.24"]),
    Q("Q09", "Dados", "Os dados em repouso são criptografados, com gestão segura das chaves?", 3, ["dados", "nuvem"],
      "Política de criptografia e gestão de chaves.", ["CMN art. 3º §2º II", "ISO A.8.24"]),
    Q("Q10", "Dados", "Os nossos dados são segregados dos de outros clientes (lógica ou fisicamente)?", 3, ["dados", "nuvem"],
      "Descrição da arquitetura de segregação.", ["CMN art. 17", "LGPD art. 46"]),
    Q("Q11", "Continuidade", "Há backup com teste de restauração documentado no último ano?", 2, ["always"],
      "Relatório do teste de restauração com data.", ["CMN art. 3º §2º VII", "ISO A.8.13"]),
    Q("Q12", "Incidentes", "Existe plano de resposta a incidentes documentado e testado?", 2, ["always"],
      "Plano e registro do último teste.", ["CMN art. 6º", "ISO A.5.24"]),
    Q("Q13", "Incidentes", "O fornecedor se compromete a nos notificar de incidentes em prazo que permita cumprir os 3 dias úteis da ANPD?", 3, ["dados"],
      "Cláusula contratual ou política com o prazo de notificação.", ["LGPD art. 48", "Res. ANPD 15/2024", "CMN art. 3º VII"]),
    Q("Q14", "Incidentes", "O histórico de incidentes dos últimos 12 meses é compartilhado conosco?", 1, ["always"],
      "Relatório de incidentes do período.", ["CMN art. 22"]),
    Q("Q15", "Continuidade", "Há plano de continuidade e recuperação de desastres testado todo ano, com RTO e RPO definidos?", 3, ["always"],
      "Plano e relatório do último teste, com RTO/RPO.", ["CMN art. 12 e art. 19", "ISO A.5.30"]),
    Q("Q16", "Continuidade", "O RTO do fornecedor é compatível com a criticidade do serviço para nós?", 2, ["always"],
      "RTO informado e aceito pelo responsável interno.", ["CMN art. 20"]),
    Q("Q17", "Vulnerabilidades", "As vulnerabilidades são tratadas em prazos definidos e medidos?", 2, ["always"],
      "Política de correção e relatório de métricas.", ["CMN art. 3º §8º", "ISO A.8.8"]),
    Q("Q18", "Vulnerabilidades", "Há teste de intrusão independente nos últimos 12 meses, com os achados corrigidos?", 2, ["nuvem", "acesso", "dados"],
      "Sumário do teste de intrusão e plano de correção.", ["ISO A.8.8"]),
    Q("Q19", "Vulnerabilidades", "O software entregue é desenvolvido com práticas seguras (revisão de código e testes de segurança)?", 1, ["nuvem"],
      "Descrição do ciclo de desenvolvimento seguro.", ["CMN art. 3º §3º", "ISO A.8.25"]),
    Q("Q20", "Subcontratados", "Há lista de subcontratados que acessam os nossos dados, com aviso prévio de mudanças?", 3, ["subcontrata"],
      "Lista atualizada e cláusula de notificação.", ["CMN art. 17", "LGPD art. 39", "ISO A.5.21"]),
    Q("Q21", "Subcontratados", "As obrigações de segurança e privacidade são repassadas aos subcontratados?", 2, ["subcontrata"],
      "Contratos ou aditivos com os subcontratados (trechos relevantes).", ["ISO A.5.21"]),
    Q("Q22", "Privacidade", "Existe acordo de tratamento de dados (DPA) assinado, com tratamento somente sob as nossas instruções?", 3, ["dados"],
      "DPA assinado.", ["LGPD art. 39 e art. 42", "ISO A.5.34"]),
    Q("Q23", "Privacidade", "Os países e regiões onde os dados são armazenados e tratados estão informados e documentados?", 3, ["exterior", "nuvem"],
      "Lista de países e regiões no contrato.", ["CMN art. 17", "LGPD art. 33"]),
    Q("Q24", "Privacidade", "A transferência internacional tem base legal e salvaguardas documentadas?", 3, ["exterior"],
      "Mecanismo de transferência e avaliação.", ["LGPD art. 33"]),
    Q("Q25", "Privacidade", "Ao fim do contrato, os dados são devolvidos e eliminados com segurança, com certificado de eliminação?", 3, ["dados"],
      "Cláusula de saída e modelo de certificado de eliminação.", ["LGPD art. 15 e art. 16", "CMN art. 17", "ISO A.8.10"]),
    Q("Q26", "Privacidade", "Os pedidos de titulares que chegam ao fornecedor são repassados a nós em prazo definido?", 2, ["dados"],
      "Procedimento e prazo.", ["LGPD art. 18"]),
    Q("Q27", "Privacidade", "Dados sensíveis têm controle reforçado (acesso restrito, registro e criptografia)?", 3, ["sensiveis"],
      "Descrição dos controles para dados sensíveis.", ["LGPD art. 11"]),
    Q("Q28", "Pessoas", "Quem acessa os dados faz treinamento periódico de segurança e passa por verificação de antecedentes?", 2, ["dados", "acesso"],
      "Registros de treinamento e política de contratação.", ["ISO A.6.3"]),
    Q("Q29", "Pessoas", "Os colaboradores assinam acordos de confidencialidade?", 2, ["always"],
      "Modelo do termo de confidencialidade.", ["ISO A.6.6"]),
    Q("Q30", "Transparência", "O contrato nos dá acesso a informações, certificações e relatórios de auditoria para monitorar o serviço?", 3, ["always"],
      "Cláusula contratual de acesso e auditoria.", ["CMN art. 17 e art. 21", "ISO A.5.22"]),
    Q("Q31", "Transparência", "O fornecedor nos mantém informados de limitações que afetem o serviço ou o cumprimento da lei?", 2, ["always"],
      "Cláusula contratual e canal de comunicação.", ["CMN art. 17"]),
    Q("Q32", "Continuidade", "Existe plano de saída e transição (portabilidade dos dados e apoio à migração)?", 2, ["always"],
      "Plano de saída ou cláusula de transição.", ["CMN art. 17"]),
    Q("Q33", "Infraestrutura", "O ambiente (data center) tem controle de acesso físico e redundância adequados?", 2, ["nuvem"],
      "Relatório de auditoria ou descrição do data center.", ["ISO A.5.23"]),
]
BY_ID: Dict[str, Question] = {q.id: q for q in QUESTIONS}


@dataclass(frozen=True)
class Clause:
    id: str
    text: str
    bcb_only: bool = False            # só se aplica quando a contratante é supervisionada pelo Banco Central
    required_for: Tuple[str, ...] = ("critico", "alto")
    short: str = ""                   # nome curto para relatórios


CLAUSES: List[Clause] = [
    Clause("C01", "Países e regiões em que os serviços são prestados e os dados armazenados e tratados", short="países e regiões"),
    Clause("C02", "Medidas de segurança na transmissão e no armazenamento dos dados", short="segurança na transmissão e no armazenamento"),
    Clause("C03", "Segregação dos dados e controles de acesso durante a vigência do contrato", short="segregação de dados e controle de acesso"),
    Clause("C04", "No fim do contrato: transferência dos dados ao novo prestador ou à contratante e eliminação pelo prestador anterior após confirmar integridade e disponibilidade",
           short="devolução e eliminação dos dados no fim do contrato"),
    Clause("C05", "Acesso da contratante a informações, certificações, relatórios de auditoria e recursos de gestão para monitorar o serviço",
           short="acesso a relatórios, certificações e auditorias"),
    Clause("C06", "Obrigação do prestador de notificar a subcontratação de serviços relevantes", short="notificação de subcontratados"),
    Clause("C07", "Acesso do Banco Central a contratos, documentação, dados armazenados e informações de tratamento", True, short="acesso do Banco Central"),
    Clause("C08", "Adoção das medidas determinadas pelo Banco Central", True, short="medidas determinadas pelo Banco Central"),
    Clause("C09", "Obrigação do prestador de manter a contratante informada de limitações que afetem o serviço ou o cumprimento da lei",
           short="informar limitações do serviço"),
    Clause("C10", "Em caso de resolução da contratante: acesso integral aos dados pelo responsável pela resolução", True, short="acesso aos dados na resolução"),
    Clause("C11", "Aviso prévio de 30 dias do prestador para encerrar o serviço em caso de inadimplência ou resolução da contratante", True, short="aviso prévio de 30 dias"),
    Clause("C12", "Acordo de tratamento de dados pessoais (DPA): tratamento só sob instrução, confidencialidade, notificação de incidentes e apoio aos titulares",
           False, ("critico", "alto", "medio"), "acordo de tratamento de dados (DPA)"),
]
CLAUSE_BY_ID = {c.id: c for c in CLAUSES}
