"""Validação de CNPJ (inclui o formato alfanumérico). Dígito verificador correto NÃO prova que a empresa existe."""
from __future__ import annotations

import re

_W1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_W2 = [6] + _W1


def _dv(chars: str, weights) -> int:
    rest = sum((ord(c) - 48) * w for c, w in zip(chars, weights)) % 11   # letras valem ord - 48 (A = 17)
    return 0 if rest < 2 else 11 - rest


def valid_cnpj(value) -> bool:
    c = re.sub(r"[.\-/\s]", "", str(value or "").upper())
    if not re.fullmatch(r"[0-9A-Z]{12}\d{2}", c) or len(set(c)) == 1:
        return False
    d1 = _dv(c[:12], _W1)
    d2 = _dv(c[:12] + str(d1), _W2)
    return c[12:] == f"{d1}{d2}"


def make_cnpj(base12: str) -> str:
    """Gera um CNPJ com dígitos corretos (só para exemplos e testes)."""
    base = re.sub(r"[.\-/\s]", "", base12.upper())[:12].ljust(12, "0")
    d1 = _dv(base, _W1)
    return base + str(d1) + str(_dv(base + str(d1), _W2))
