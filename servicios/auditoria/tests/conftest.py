"""Pruebas del servicio de auditoría: base real, cada prueba se deshace con ROLLBACK."""

import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

os.environ.setdefault("AUTH_MODO", "desarrollo")

import psycopg
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from medicitas_comun import conexion
from psycopg.rows import dict_row

from app.main import app

CR = timezone(timedelta(hours=-6))  # Costa Rica no tiene horario de verano


def como(usuario_id) -> dict:
    return {"X-Usuario-Id": str(usuario_id)}


@pytest.fixture
def con():
    c = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    c.execute("SELECT 1")
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def cliente(con):
    def conexion_de_prueba(request: Request):
        request.state.tras_commit = []
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
    """Clínica A (administrador, recepción, profesional, dos pacientes, un servicio) y clínica B (administrador y un paciente)."""
    w = SimpleNamespace()
    sufijo = uuid.uuid4().hex[:8]
    roles = {f["codigo"]: f["id"] for f in con.execute("SELECT id, codigo FROM rol")}

    def clinica(n):
        return _insertar(con, "INSERT INTO clinica (nombre, identificador, zona_horaria) VALUES (%s, %s, 'America/Costa_Rica')", n, f"{n}-{sufijo}")

    def usuario(clin, rol, nombre):
        uid = uuid.uuid4()
        con.execute("INSERT INTO usuario (id, clinica_id, rol_id, keycloak_sub, nombre) VALUES (%s,%s,%s,%s,%s)",
                    (uid, clin, roles[rol], str(uid), nombre))
        return uid

    def paciente(clin, ident, nombre):
        return _insertar(con, "INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento) VALUES (%s,%s,%s,'1990-01-01')",
                         clin, f"{ident}-{sufijo}", nombre)

    w.a, w.b = clinica("a"), clinica("b")
    w.admin, w.recepcion = usuario(w.a, "ADM_CLINICA", "Admin A"), usuario(w.a, "RECEPCION", "Recepción A")
    w.profesional_usuario = usuario(w.a, "PROFESIONAL", "Dra. Uno")
    w.admin_b, w.plataforma = usuario(w.b, "ADM_CLINICA", "Admin B"), usuario(None, "ADM_PLATAFORMA", "Plataforma")
    w.ana, w.beto, w.ajeno = paciente(w.a, "111", "Ana Solís"), paciente(w.a, "222", "Beto Mora"), paciente(w.b, "333", "Ajeno Pérez")

    esp = _insertar(con, "INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, 'General')", w.a)
    w.servicio = _insertar(con, "INSERT INTO servicio (clinica_id, nombre, duracion_minutos, especialidad_id) VALUES (%s,'Consulta',30,%s)", w.a, esp)
    w.profesional = _insertar(con, "INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado) VALUES (%s,%s,%s,'C-1')",
                              w.a, w.profesional_usuario, esp)
    con.execute("INSERT INTO profesional_servicio (clinica_id, profesional_id, servicio_id) VALUES (%s,%s,%s)", (w.a, w.profesional, w.servicio))

    def registro(clin, usuario_id, paciente_id, cuando, accion="LECTURA", recurso="CONTACTO_PACIENTE"):
        return _insertar(con, """INSERT INTO registro_auditoria (clinica_id, usuario_id, paciente_id, accion, recurso, ocurrido_en)
                                 VALUES (%s,%s,%s,%s,%s,%s)""", clin, usuario_id, paciente_id, accion, recurso, cuando)

    def cita(inicio, estado="RESERVADA", paciente_id=None, clin=None):
        extra = ("cancelada_por, cancelada_en, motivo_cancelacion", ", %s, now(), 'prueba'") if estado == "CANCELADA" else ("", "")
        cols = "clinica_id, paciente_id, profesional_id, servicio_id, inicio, fin, estado, creada_por" + (", " + extra[0] if extra[0] else "")
        params = [w.a, paciente_id or w.ana, w.profesional, w.servicio, inicio, inicio + timedelta(minutes=30), estado, w.admin]
        if extra[0]:
            params.append(w.admin)
        return con.execute(f"INSERT INTO cita ({cols}) VALUES (%s,%s,%s,%s,%s,%s,%s,%s{extra[1]}) RETURNING id", params).fetchone()["id"]

    w.registro, w.cita = registro, cita
    return w
