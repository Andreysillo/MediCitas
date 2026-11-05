"""Nivel de aislamiento, tiempos de espera y reintento por deadlock."""

import os
import threading
import time

import httpx
import psycopg
import pytest
from conftest import servidor_real
from fastapi import FastAPI
from fastapi.testclient import TestClient
from medicitas_comun import CONEXION, conexion, reintentar_si_deadlock
from psycopg import errors

from app.main import app


def test_el_nivel_de_aislamiento_activo_es_read_committed():
    """La reserva depende de READ COMMITTED (ver medicitas_comun/app.py): si alguien cambia el pool, esta prueba avisa."""
    with TestClient(app):
        with app.state.pool.connection() as con:
            assert con.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] == "read committed"
            assert con.execute("SHOW lock_timeout").fetchone()["lock_timeout"] == "5s"
            assert con.execute("SHOW idle_in_transaction_session_timeout").fetchone()["idle_in_transaction_session_timeout"] == "30s"


class ConexionFalsa:
    rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


def test_reintento_tras_un_deadlock():
    con, llamadas = ConexionFalsa(), []

    def operacion():
        llamadas.append(1)
        if len(llamadas) < 3:
            raise errors.DeadlockDetected("deadlock detected")
        return "listo"

    assert reintentar_si_deadlock(con, operacion) == "listo"
    assert len(llamadas) == 3 and con.rollbacks == 2           # se deshizo cada intento fallido


def test_si_el_deadlock_persiste_el_error_sube():
    con = ConexionFalsa()

    def siempre():
        raise errors.DeadlockDetected("deadlock detected")

    with pytest.raises(errors.DeadlockDetected):
        reintentar_si_deadlock(con, siempre, intentos=2)
    assert con.rollbacks == 2


def test_otros_errores_no_se_reintentan():
    con, llamadas = ConexionFalsa(), []

    def operacion():
        llamadas.append(1)
        raise errors.UniqueViolation("duplicado")

    with pytest.raises(errors.UniqueViolation):
        reintentar_si_deadlock(con, operacion)
    assert len(llamadas) == 1 and con.rollbacks == 0


def test_deadlock_real_dos_transacciones_que_se_piden_los_bloqueos_al_reves(mundo_real):
    """Dos transacciones toman dos filas en orden opuesto: Postgres detecta el ciclo y aborta una (40P01).
    Con el reintento, las dos terminan. Es el único modo de probar el manejo de deadlock sin esperar a que ocurra solo."""
    a, b = mundo_real.prof, mundo_real.prof2
    intentos = []

    def transaccion(primero, segundo):
        con = psycopg.connect(os.environ["DATABASE_URL"])
        n = 0

        def operacion():
            nonlocal n
            n += 1
            con.execute("SELECT 1 FROM profesional WHERE id = %s FOR UPDATE", (primero,))
            time.sleep(0.4)                                    # da tiempo a que la otra tome su primera fila
            con.execute("SELECT 1 FROM profesional WHERE id = %s FOR UPDATE", (segundo,))
            con.commit()

        try:
            reintentar_si_deadlock(con, operacion)
        finally:
            intentos.append(n)
            con.close()

    hilos = [threading.Thread(target=transaccion, args=(a, b)), threading.Thread(target=transaccion, args=(b, a))]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(30)
    assert not any(h.is_alive() for h in hilos)
    assert sorted(intentos)[0] == 1 and sorted(intentos)[1] >= 2     # una pasó a la primera; la víctima tuvo que repetir


def test_el_commit_ocurre_antes_de_enviar_la_respuesta():
    """Si la respuesta saliera antes del COMMIT, quien consulta justo después de un 201 no vería su propia reserva (I7, I8)
    y un commit fallido llegaría como éxito. Se simula un COMMIT lento: el cliente no debe recibir nada hasta que termine."""
    terminado = []
    mini = FastAPI()

    def conexion_con_commit_lento():
        yield None
        time.sleep(0.5)                       # el COMMIT
        terminado.append(True)

    mini.dependency_overrides[conexion] = conexion_con_commit_lento

    @mini.get("/ruta")
    def ruta(con=CONEXION):
        return {"ok": True}

    with servidor_real(mini) as url:
        assert httpx.get(f"{url}/ruta").status_code == 200
        assert terminado == [True], "la respuesta llegó antes de que terminara el código posterior al yield (¿falta scope=\"function\"?)"
