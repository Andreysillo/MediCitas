"""La prueba de carrera: varios clientes concurrentes compiten por el mismo espacio y gana exactamente uno.

Usa un servidor uvicorn REAL (no el TestClient) y datos CONFIRMADOS, porque lo que se prueba es el comportamiento
del motor con varias conexiones a la vez, incluido que el COMMIT ocurra antes de enviar la respuesta.
Es reproducible: cada ronda alinea a los clientes en una barrera para que el envío sea simultáneo.
"""

import os
import threading
from datetime import timedelta

import httpx
import psycopg
import pytest
from conftest import como, proximo, servidor_real
from psycopg.rows import dict_row

from app.main import app

RONDAS = 12
CLIENTES = 8


@pytest.fixture(scope="module")
def servidor():
    with servidor_real(app) as url:
        yield url


def en_paralelo(servidor, tareas):
    """Ejecuta cada tarea (una función que recibe un httpx.Client) en su propio hilo, todas a la vez. Devuelve sus resultados."""
    barrera, resultados = threading.Barrier(len(tareas)), [None] * len(tareas)

    def correr(i, tarea):
        with httpx.Client(base_url=servidor, timeout=30) as c:
            barrera.wait()
            resultados[i] = tarea(c)

    hilos = [threading.Thread(target=correr, args=(i, t)) for i, t in enumerate(tareas)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(60)
    assert not any(h.is_alive() for h in hilos), "una solicitud quedó colgada"
    return resultados


def confirmado(sql, *params):
    """Consulta desde una conexión APARTE de la API: solo ve lo que ya se confirmó (COMMIT)."""
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as c:
        return c.execute(sql, params).fetchall()


def horario_todos_los_dias(w, *profesionales):
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        for prof in profesionales:
            for dia in range(1, 8):
                c.execute("INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin) VALUES (%s,%s,%s,'08:00','18:00')",
                          (w.clinica_a, prof, dia))


def nuevos_pacientes(w, n):
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as c:
        return [c.execute("INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento) VALUES (%s,%s,%s,'1990-01-01') RETURNING id",
                          (w.clinica_a, f"carrera-{i}", f"Paciente {i}")).fetchone()[0] for i in range(n)]


def solicitud(w, paciente, inicio, profesional=None):
    return {"paciente_id": str(paciente), "profesional_id": str(profesional or w.prof),
            "servicio_id": str(w.servicio), "inicio": inicio.isoformat()}


VIGENTES = "estado IN ('RESERVADA','ATENDIDA','AUSENTE')"


def test_ocho_clientes_compiten_por_el_ultimo_espacio_y_gana_uno_I1(servidor, mundo_real):
    w = mundo_real
    horario_todos_los_dias(w, w.prof)
    # Un paciente distinto por cliente: así el choque es solo por el profesional (I1), no por el paciente (I2).
    pacientes = nuevos_pacientes(w, CLIENTES)

    for ronda in range(RONDAS):
        inicio = proximo(1, 8) + timedelta(days=7 * (ronda // 4), minutes=30 * (ronda % 4))      # un espacio distinto por ronda
        respuestas = en_paralelo(servidor, [
            lambda c, p=p: c.post("/citas", headers=como(w.recepcion), json=solicitud(w, p, inicio)) for p in pacientes])

        estados = sorted(r.status_code for r in respuestas)
        assert estados == [201] + [409] * (CLIENTES - 1), f"ronda {ronda}: {estados}"
        assert all(r.json()["restriccion"] == "cita_sin_solape_profesional" for r in respuestas if r.status_code == 409)

        filas = confirmado(f"SELECT id FROM cita WHERE profesional_id = %s AND inicio = %s AND {VIGENTES}", w.prof, inicio)
        assert len(filas) == 1                                                                    # sin duplicados
        # El COMMIT ocurrió antes de la respuesta: otra conexión ya ve la cita al recibir el 201.
        assert str(filas[0]["id"]) == next(r for r in respuestas if r.status_code == 201).json()["id"]


def test_un_paciente_no_puede_estar_en_dos_consultas_a_la_vez_I2(servidor, mundo_real):
    w = mundo_real
    horario_todos_los_dias(w, w.prof, w.prof2)
    for ronda in range(RONDAS):
        inicio = proximo(2, 8) + timedelta(days=7 * (ronda // 4), minutes=30 * (ronda % 4))
        # 4 clientes con el MISMO paciente, repartidos entre dos profesionales: ninguno choca por profesional con otro
        # de distinto profesional, pero el paciente solo puede tener una.
        tareas = [lambda c, p=p: c.post("/citas", headers=como(w.recepcion), json=solicitud(w, w.paciente, inicio, p))
                  for p in (w.prof, w.prof2, w.prof, w.prof2)]
        estados = sorted(r.status_code for r in en_paralelo(servidor, tareas))
        assert estados == [201, 409, 409, 409], f"ronda {ronda}: {estados}"
        assert len(confirmado(f"SELECT id FROM cita WHERE paciente_id = %s AND inicio = %s AND {VIGENTES}", w.paciente, inicio)) == 1


def test_un_bloqueo_y_una_reserva_simultaneos_nunca_dejan_una_cita_colada_I3(servidor, mundo_real):
    """Alguien crea un bloqueo mientras otra persona reserva dentro de él. Los dos resultados correctos son:
    la reserva se rechazó (422) o la reserva se concedió y el bloqueo la lista como conflicto. Lo incorrecto sería una
    cita dentro del bloqueo que el bloqueo no menciona."""
    w = mundo_real
    horario_todos_los_dias(w, w.prof)
    vistas = {"reserva_rechazada": 0, "cita_listada_como_conflicto": 0}
    for ronda in range(RONDAS * 2):
        base = proximo(3, 9) + timedelta(days=7 * ronda)
        bloqueo = {"inicio": base.isoformat(), "fin": (base + timedelta(hours=2)).isoformat(), "motivo": "Permiso"}
        r_bloqueo, r_reserva = en_paralelo(servidor, [
            lambda c: c.post(f"/profesionales/{w.prof}/bloqueos", headers=como(w.admin), json=bloqueo),
            lambda c: c.post("/citas", headers=como(w.recepcion), json=solicitud(w, w.paciente, base + timedelta(minutes=30))),
        ])
        assert r_bloqueo.status_code == 201, r_bloqueo.text
        if r_reserva.status_code == 201:
            assert r_reserva.json()["id"] in [c["id"] for c in r_bloqueo.json()["conflictos"]], f"ronda {ronda}: cita colada"
            vistas["cita_listada_como_conflicto"] += 1
        else:
            assert r_reserva.status_code == 422 and "bloqueo" in r_reserva.json()["detalle"], f"ronda {ronda}: {r_reserva.text}"
            vistas["reserva_rechazada"] += 1
    print("\nDesenlaces de la carrera bloqueo-reserva:", vistas)
