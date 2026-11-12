"""Plan y tiempo de las consultas más usadas de la agenda (T15). No es una prueba: pytest no lo recoge.

Se corre con el SQL real de app/, contra una base con volumen (db/pruebas/historial_sintetico.sql):

    docker compose --profile pruebas run --rm pruebas-agenda python -m tests.medir_consultas          # resumen
    docker compose --profile pruebas run --rm pruebas-agenda python -m tests.medir_consultas --plan   # planes completos

Cada consulta se ejecuta 50 veces sobre la misma conexión y como la ejecuta la API: la de espacios sin preparar (ver
app/espacios.py) y las demás preparadas, como hace psycopg a partir de la quinta vez.
"""

import os
import statistics
import sys
import time
from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row

from app.conflictos import _CITAS_RESERVADAS_FUTURAS
from app.espacios import PASO_MINUTOS, _SQL as ESPACIOS

# Copia de la consulta de plataforma que cuenta las citas pendientes al dar de baja a un usuario (RF2, usuarios.py).
_PENDIENTES_AL_DAR_DE_BAJA = """
    SELECT count(*) AS n FROM cita c JOIN profesional p ON p.id = c.profesional_id AND p.clinica_id = c.clinica_id
     WHERE p.usuario_id = %(usuario)s AND c.clinica_id = %(clinica)s AND c.estado = 'RESERVADA' AND c.fin > now()
"""
# La comprobación de bloqueos de la reserva (RF9, reserva.py), aislada.
_RESERVA_EN_BLOQUEO = """
    SELECT EXISTS (SELECT 1 FROM bloqueo_agenda b
                    WHERE b.profesional_id = %(profesional)s
                      AND tstzrange(b.inicio, b.fin, '[)') && tstzrange(%(inicio)s, %(fin)s, '[)'))
"""
_LISTAR_BLOQUEOS = "SELECT id FROM bloqueo_agenda WHERE profesional_id = %(profesional)s AND fin > now() ORDER BY inicio"


def main(detalle: bool) -> None:
    con = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True)
    laura = con.execute(
        """SELECT p.id, p.usuario_id, p.clinica_id, ps.servicio_id, s.duracion_minutos, c.zona_horaria
             FROM profesional p JOIN usuario u ON u.id = p.usuario_id JOIN clinica c ON c.id = p.clinica_id
             JOIN profesional_servicio ps ON ps.profesional_id = p.id JOIN servicio s ON s.id = ps.servicio_id
            WHERE u.nombre LIKE '%Laura%' ORDER BY s.duracion_minutos LIMIT 1""").fetchone()
    lunes = date.today() + timedelta(days=7)
    while lunes.isoweekday() != 1:
        lunes += timedelta(days=1)
    nueve = con.execute("SELECT (%s::date + time '09:00') AT TIME ZONE %s AS t", (lunes, laura["zona_horaria"])).fetchone()["t"]

    def espacios(profesional, dias):
        return {"clinica": laura["clinica_id"], "servicio": laura["servicio_id"], "profesional": profesional, "ignorar": None,
                "zona": laura["zona_horaria"], "desde": lunes, "dias": dias,
                "duracion": timedelta(minutes=laura["duracion_minutos"]), "paso": timedelta(minutes=PASO_MINUTOS)}

    consultas = {
        "RF7: un profesional, un día": (ESPACIOS, espacios(laura["id"], 1)),
        "RF8: toda la clínica, 7 días": (ESPACIOS, espacios(None, 7)),
        "RF9: ¿la reserva cae en un bloqueo?": (_RESERVA_EN_BLOQUEO, {"profesional": laura["id"], "inicio": nueve,
                                                                     "fin": nueve + timedelta(minutes=30)}),
        "RF6: listar los bloqueos de un profesional": (_LISTAR_BLOQUEOS, {"profesional": laura["id"]}),
        "RF5/RF6: citas reservadas que quedan en conflicto": (_CITAS_RESERVADAS_FUTURAS, {"clinica": laura["clinica_id"],
                                                                                         "profesional": laura["id"]}),
        "RF2 (plataforma): citas pendientes al dar de baja": (_PENDIENTES_AL_DAR_DE_BAJA, {"usuario": laura["usuario_id"],
                                                                                          "clinica": laura["clinica_id"]}),
    }

    volumen = con.execute("SELECT (SELECT count(*) FROM cita) AS citas, (SELECT count(*) FROM bloqueo_agenda) AS bloqueos").fetchone()
    print(f"Volumen: {volumen['citas']} citas, {volumen['bloqueos']} bloqueos")
    for nombre, (sql, p) in consultas.items():
        plan = [r["QUERY PLAN"] for r in con.execute("EXPLAIN (ANALYZE, BUFFERS, COSTS OFF) " + sql, p)]
        tiempos = []
        for _ in range(50):
            t = time.perf_counter()
            con.execute(sql, p, prepare=False if sql is ESPACIOS else None).fetchall()
            tiempos.append((time.perf_counter() - t) * 1000)
        accesos = [l.strip() for l in plan if " on cita" in l or " on bloqueo_agenda" in l]
        print(f"\n### {nombre}\n    mediana {statistics.median(tiempos):.2f} ms · p95 {sorted(tiempos)[47]:.2f} ms")
        for linea in plan if detalle else accesos:
            print("   ", linea[:160])


if __name__ == "__main__":
    main("--plan" in sys.argv)
