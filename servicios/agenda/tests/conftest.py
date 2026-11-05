"""Preparación común de las pruebas del servicio de agenda.

Las pruebas usan la base REAL (Postgres con el esquema aplicado), porque lo que se prueba son restricciones
del motor y SQL. Cada prueba arma sus propios datos y al terminar todo se deshace con ROLLBACK: no depende de la
semilla ni deja basura.
"""

import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("AUTH_MODO", "desarrollo")

import psycopg
import pytest
from fastapi.testclient import TestClient
from medicitas_comun import conexion
from psycopg.rows import dict_row

from app.main import app

# Costa Rica no tiene horario de verano: siempre UTC-6. Las clínicas de prueba usan esa zona.
CR = timezone(timedelta(hours=-6))


def proximo(dia_iso: int, hora: int, minuto: int = 0) -> datetime:
    """El primer día de la semana pedida (1 lunes ... 7 domingo) a más de 7 días de hoy, a esa hora local."""
    d = (datetime.now(CR) + timedelta(days=7)).date()
    while d.isoweekday() != dia_iso:
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, hora, minuto, tzinfo=CR)


def como(usuario_id) -> dict:
    """Cabecera que identifica al usuario en modo desarrollo (ver medicitas_comun/sesion.py)."""
    return {"X-Usuario-Id": str(usuario_id)}


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
def cliente(con):
    def conexion_de_prueba():
        # Un punto de guardado por solicitud: si la ruta falla (409, 422...), solo se deshace esa solicitud
        # y la prueba puede seguir usando la misma conexión.
        with con.transaction():
            yield con

    app.dependency_overrides[conexion] = conexion_de_prueba
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _insertar(con, sql, *params):
    return con.execute(sql + " RETURNING id", params).fetchone()["id"]


@pytest.fixture
def mundo(con):
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

    w.cita = cita
    return w
