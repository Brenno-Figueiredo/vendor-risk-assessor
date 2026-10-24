#!/usr/bin/env python3
"""VendorRisk - avaliação de risco de fornecedores (gestão de riscos de terceiros).
Exemplos:
    python app.py demo --html relatorio.html --plan plano.csv --scorecards fichas
    python app.py show f03 --demo                         # ficha de um fornecedor
    python app.py request --vendors fornecedores.csv      # questionários para enviar aos fornecedores
    python app.py assess --vendors fornecedores.csv --answers respostas.csv --clauses clausulas.csv
"""
import sys

from vendorrisk.cli import main

if __name__ == "__main__":
    sys.exit(main())
