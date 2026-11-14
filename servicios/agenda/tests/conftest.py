"""Preparación común de las pruebas del servicio de agenda.

Las pruebas usan la base REAL (Postgres con el esquema aplicado), porque lo que se prueba son restricciones
del motor y SQL. Cada prueba arma sus propios datos y al terminar todo se deshace con ROLLBACK: no depende de la
semilla ni deja basura.
"""

import os
import socket
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("AUTH_MODO", "desarrollo")

import psycopg
import pytest
import uvicorn
from fastapi import Request
from fastapi.testclient import TestClient
from medicitas_comun import conexion
from psycopg.rows import dict_row

from app import cache
from app.main import app

# Costa Rica no tiene horario de verano: siempre UTC-6. Las clínicas de prueba usan esa zona.
CR = timezone(timedelta(hours=-6))


@contextmanager
def servidor_real(aplicacion):
    """Levanta `aplicacion` en un uvicorn de verdad (puerto libre, otro hilo) y devuelve su URL. A diferencia del
    TestClient, la respuesta viaja por una conexión real y el cliente no espera a que termine el código posterior."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        puerto = sock.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(aplicacion, host="127.0.0.1", port=puerto, log_level="warning"))
    hilo = threading.Thread(target=srv.run, daemon=True)
    hilo.start()
    while not srv.started:
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{puerto}"
    finally:
        srv.should_exit = True
        hilo.join(10)


def proximo(dia_iso: int, hora: int, minuto: int = 0) -> datetime:
    """El primer día de la semana pedida (1 lunes ... 7 domingo) a más de 7 días de hoy, a esa hora local."""
    d = (datetime.now(CR) + timedelta(days=7)).date()
    while d.isoweekday() != dia_iso:
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, hora, minuto, tzinfo=CR)


def como(usuario_id) -> dict:
    """Cabecera que identifica al usuario en modo desarrollo (ver medicitas_comun/sesion.py)."""
    return {"X-Usuario-Id": str(usuario_id)}


def _como_rol_del_servicio(con):
    """Con ROL_PRUEBAS, la solicitud corre con el rol de menor privilegio del servicio (migración 011), como en producción.
    El resto de la prueba (armar datos, comprobar resultados) sigue como superusuario."""
    rol = os.environ.get("ROL_PRUEBAS")
    if rol:
        con.execute(psycopg.sql.SQL("SET LOCAL ROLE {}").format(psycopg.sql.Identifier(rol)))


@pytest.fixture
def con():
    c = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    # Abre la transacción exterior. Sin esto, `con.transaction()` de abajo haría un COMMIT real al salir en vez
    # de un simple punto de guardado.
    c.execute("SELECT 1")
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def cliente(con, monkeypatch):
    # Sin caché: estas pruebas escriben con SQL directo y nunca confirman, así que nada invalidaría. La caché se prueba
    # en test_cache.py, con Redis y commits de verdad.
    monkeypatch.setattr(cache, "_redis", lambda: None)

    def conexion_de_prueba(request: Request):
        request.state.tras_commit = []
        # Un punto de guardado por solicitud: si la ruta falla (409, 422...), solo se deshace esa solicitud
        # y la prueba puede seguir usando la misma conexión.
        with con.transaction():
            _como_rol_del_servicio(con)
            yield con
        con.execute("RESET ROLE")   # solo se llega aquí si la solicitud salió bien; si falló, el rollback ya lo deshizo

    app.dependency_overrides[conexion] = conexion_de_prueba
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _insertar(con, sql, *params):
    return con.execute(sql + " RETURNING id", params).fetchone()["id"]


def construir_mundo(con):
    """Dos clínicas. En la A: administrador, recepción, dos profesionales, un servicio y un paciente.
    En la B: un administrador. Más un administrador de plataforma."""
    w = SimpleNamespace()
    sufijo = uuid.uuid4().hex[:8]
    roles = {f["codigo"]: f["id"] for f in con.execute("SELECT id, codigo FROM rol")}

    def clinica(nombre):
        return _insertar(con, "INSERT INTO clinica (nombre, identificador, zona_horaria) VALUES (%s, %s, 'America/Costa_Rica')",
                         nombre, f"{nombre}-{sufijo}")

    def usuario(clin, rol, nombre, activo=True):
        uid = uuid.uuid4()
        con.execute("INSERT INTO usuario (id, clinica_id, rol_id, keycloak_sub, nombre, activo) VALUES (%s,%s,%s,%s,%s,%s)",
                    (uid, clin, roles[rol], str(uid), nombre, activo))
        return uid

    w.clinica_a, w.clinica_b = clinica("a"), clinica("b")
    w.admin = usuario(w.clinica_a, "ADM_CLINICA", "Admin A")
    w.recepcion = usuario(w.clinica_a, "RECEPCION", "Recepción A")
    w.admin_otra_clinica = usuario(w.clinica_b, "ADM_CLINICA", "Admin B")
    w.plataforma = usuario(None, "ADM_PLATAFORMA", "Plataforma")
    w.inactivo = usuario(w.clinica_a, "RECEPCION", "Dado de baja", activo=False)

    especialidad = _insertar(con, "INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, 'General')", w.clinica_a)
    w.servicio = _insertar(
        con, "INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s, 'Consulta', 30, %s)",
        w.clinica_a, especialidad)

    def profesional(nombre):
        uid = usuario(w.clinica_a, "PROFESIONAL", nombre)
        pid = _insertar(con, "INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado) VALUES (%s,%s,%s,'COL-1')",
                        w.clinica_a, uid, especialidad)
        con.execute("INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES (%s,%s,%s)",
                    (w.clinica_a, pid, w.servicio))
        return uid, pid

    w.usuario_prof, w.prof = profesional("Dra. Uno")
    w.usuario_prof2, w.prof2 = profesional("Dr. Dos")
    w.paciente = _insertar(
        con, "INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento) VALUES (%s, '1-1111-1111', 'Paciente Uno', '1990-01-01')",
        w.clinica_a)

    def cita(inicio: datetime, minutos: int = 30, estado: str = "RESERVADA", profesional=None):
        cancelada = ("%s, now(), 'prueba'" if estado == "CANCELADA" else "NULL, NULL, NULL")
        return _insertar(
            con,
            f"""INSERT INTO cita (clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por,
                                  cancelada_por, cancelada_en, motivo_cancelacion)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,{cancelada})""",
            w.clinica_a, w.paciente, profesional or w.prof, w.servicio, inicio, inicio + timedelta(minutes=minutos), estado, w.admin,
            *([w.admin] if estado == "CANCELADA" else []))

    def nuevo_paciente():
        n = uuid.uuid4().hex[:10]
        return _insertar(con, "INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento) VALUES (%s, %s, %s, '1990-01-01')",
                         w.clinica_a, n, f"Paciente {n}")

    w.cita = cita
    w.nuevo_paciente = nuevo_paciente
    return w


def poner_horario(con, mundo, profesional, dia_iso, inicio, fin):
    con.execute("INSERT INTO horario_atencion (clinica_id, profesional_id, dia_semana, hora_inicio, hora_fin) VALUES (%s,%s,%s,%s,%s)",
                (mundo.clinica_a, profesional, dia_iso, inicio, fin))


@pytest.fixture
def mundo(con):
    """El mundo de arriba dentro de la transacción de la prueba: se deshace solo con el ROLLBACK."""
    return construir_mundo(con)


@pytest.fixture
def mundo_real():
    """El mismo mundo pero CONFIRMADO (COMMIT) en la base, para las pruebas de concurrencia: varias conexiones
    tienen que verse entre sí, y eso es imposible dentro de una transacción sin confirmar.
    Al terminar se borra todo lo que creó, hija antes que madre. Solo toca filas de sus dos clínicas nuevas."""
    c = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True)
    w = None
    try:
        with c.transaction():
            w = construir_mundo(c)
        yield w
    finally:
        if w is not None:
            clinicas = [w.clinica_a, w.clinica_b]
            with c.transaction():
                for tabla in ("cita", "bloqueo_agenda", "horario_atencion", "profesional_servicio", "profesional",
                              "servicio", "especialidad", "paciente", "usuario"):
                    c.execute(f"DELETE FROM {tabla} WHERE clinica_id = ANY(%s)", (clinicas,))
                c.execute("DELETE FROM usuario WHERE id = %s", (w.plataforma,))      # el único usuario sin clínica
                c.execute("DELETE FROM clinica WHERE id = ANY(%s)", (clinicas,))
        c.close()
