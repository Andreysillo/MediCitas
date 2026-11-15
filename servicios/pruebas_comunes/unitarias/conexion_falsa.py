"""Doble de la conexión a la base para las unitarias: anota cada consulta y responde con lo que la prueba le dio.

`ConexionFalsa([r1, r2, ...])`: la n-ésima consulta recibe `r_n`; sin más respuestas, nada (None / lista vacía).
Una respuesta es una fila (dict), una lista de filas o None. Así una prueba dice «la cita existe, la nota no» sin base.
"""

from types import SimpleNamespace


class ConexionFalsa:
    def __init__(self, respuestas=()):
        self._respuestas = list(respuestas)
        self.consultas: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.consultas.append((" ".join(sql.split()), params))
        r = self._respuestas.pop(0) if self._respuestas else None
        return SimpleNamespace(
            fetchone=lambda: (r[0] if r else None) if isinstance(r, list) else r,
            fetchall=lambda: r if isinstance(r, list) else ([r] if r else []),
        )

    def escrituras(self, tabla: str | None = None) -> list[tuple[str, object]]:
        """Las consultas que no son SELECT (opcionalmente, solo las que mencionan `tabla`)."""
        return [(s, p) for s, p in self.consultas
                if not s.upper().startswith("SELECT") and (tabla is None or tabla in s)]
