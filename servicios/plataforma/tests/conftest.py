"""Preparación de las pruebas del servicio de plataforma: base real, cada prueba se deshace con ROLLBACK."""

import os
import uuid

os.environ.setdefault("AUTH_MODO", "desarrollo")

import psycopg
import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from medicitas_comun import conexion
from psycopg.rows import dict_row

from app.keycloak import keycloak_admin
from app.main import app


class KeycloakFalso:
    """Doble de Keycloak: registra lo que se le pide y puede simular una caída o un usuario repetido."""

    def __init__(self):
        self.creados, self.eliminados = [], []
        self.falla = None  # None, "caido" o "repetido"

    def crear_usuario(self, *, usuario, nombre, contrasena, rol):
        if self.falla == "caido":
            raise HTTPException(503, "No se pudo crear el usuario en el proveedor de identidad, intenta de nuevo")
        if self.falla == "repetido":
            raise HTTPException(409, "Ya existe un usuario con ese nombre de usuario en el proveedor de identidad")
        sub = str(uuid.uuid4())
        self.creados.append({"sub": sub, "usuario": usuario, "nombre": nombre, "contrasena": contrasena, "rol": rol})
        return sub

    def eliminar_usuario(self, sub):
        self.eliminados.append(sub)


def como(usuario_id) -> dict:
    return {"X-Usuario-Id": str(usuario_id)}


@pytest.fixture
def con():
    c = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    c.execute("SELECT 1")  # abre la transacción exterior; las de la ruta pasan a ser puntos de guardado
    yield c
    c.rollback()
    c.close()


@pytest.fixture
def kc():
    return KeycloakFalso()


@pytest.fixture
def cliente(con, kc):
    def conexion_de_prueba(request: Request):
        request.state.tras_commit = []
        with con.transaction():
            yield con

    app.dependency_overrides[conexion] = conexion_de_prueba
    app.dependency_overrides[keycloak_admin] = lambda: kc
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _usuario(con, rol, clinica_id=None):
    uid = uuid.uuid4()
    con.execute(
        "INSERT INTO usuario (id, clinica_id, rol_id, keycloak_sub, nombre) SELECT %s, %s, id, %s, %s FROM rol WHERE codigo = %s",
        (uid, clinica_id, str(uid), rol, rol),
    )
    return uid


@pytest.fixture
def mundo(con):
    """Un administrador de plataforma y un administrador de clínica (de una clínica ya existente)."""
    clinica = con.execute(
        "INSERT INTO clinica (nombre, identificador, zona_horaria) VALUES ('Existente', %s, 'America/Costa_Rica') RETURNING id",
        (f"existente-{uuid.uuid4().hex[:8]}",),
    ).fetchone()["id"]

    otra = con.execute(
        "INSERT INTO clinica (nombre, identificador, zona_horaria) VALUES ('Otra', %s, 'America/Costa_Rica') RETURNING id",
        (f"otra-{uuid.uuid4().hex[:8]}",),
    ).fetchone()["id"]
    especialidad = con.execute(
        "INSERT INTO especialidad (clinica_id, nombre) VALUES (%s, 'General') RETURNING id", (clinica,)
    ).fetchone()["id"]

    class Mundo:
        clinica_id = clinica
        plataforma = _usuario(con, "ADM_PLATAFORMA")
        admin_clinica = _usuario(con, "ADM_CLINICA", clinica)
        segundo_admin = _usuario(con, "ADM_CLINICA", clinica)
        recepcion = _usuario(con, "RECEPCION", clinica)
        profesional = _usuario(con, "PROFESIONAL", clinica)
        # Un usuario de OTRA clínica: el administrador de `clinica` no debe poder verlo ni tocarlo (I5).
        admin_otra = _usuario(con, "ADM_CLINICA", otra)
        recepcion_otra = _usuario(con, "RECEPCION", otra)

    # `profesional` es un profesional registrado (fila en la tabla profesional), como lo deja RF4.
    con.execute(
        "INSERT INTO profesional (clinica_id, usuario_id, especialidad_id, numero_colegiado) VALUES (%s, %s, %s, 'COL-1')",
        (clinica, Mundo.profesional, especialidad),
    )
    return Mundo
