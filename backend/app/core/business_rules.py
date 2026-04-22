from __future__ import annotations

# Mantem a base inicial de aprovadores reconhecidos pela regra de anomalia.
KNOWN_APPROVERS = {
    "MARIA SILVA",
    "FERNANDA COSTA",
    "JOAO SOUZA",
    "ANA PAULA",
    "CARLOS LIMA",
}

# Evita aceitar como confiavel um aprovador visto poucas vezes no historico.
APPROVER_MIN_OCCURRENCES = 2
