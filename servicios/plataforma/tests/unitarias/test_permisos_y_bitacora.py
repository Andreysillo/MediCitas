"""T33: unitarias de los permisos por rol (RF17), la bitácora (RF18) y la clínica de la sesión (I5) en plataforma, SIN base de datos.

Se llaman las funciones de las rutas directamente, con una conexión falsa que anota lo que se le pide y responde lo que la
prueba le dice («la cita existe, la nota no»). Lo que decide el motor (que la fila de bitácora realmente se guarde en la
misma transacción, que los JOIN no crucen de clínica) lo prueban las de integración.
"""

import uuid
from datetime import date

import pytest
from conexion_falsa import ConexionFalsa
from fastapi import HTTPException

from app import alta, catalogo, notas, pacientes, profesionales, usuarios
from app.esquemas import DatosNota, DatosPaciente
from medicitas_comun import Sesion

CLINICA, USUARIO, PACIENTE, CITA = (uuid.uuid4() for _ in range(4))
ROLES = ["ADM_PLATAFORMA", "ADM_CLINICA", "RECEPCION", "PROFESIONAL"]


def sesion(rol="ADM_CLINICA"):
    return Sesion(USUARIO, CLINICA, rol)


def codigo_de(funcion, *args, **kwargs) -> int:
    with pytest.raises(HTTPException) as e:
        funcion(*args, **kwargs)
    return e.value.status_code


# ---------- La matriz de permisos del enunciado, un filtro por fila ----------

MATRIZ = {
    "alta de clínicas (RF1)": (alta.solo_plataforma, {"ADM_PLATAFORMA"}),
    "usuarios (RF2)": (usuarios.admin_de_clinica, {"ADM_CLINICA"}),
    "catálogo, escritura (RF3)": (catalogo.admin_de_clinica, {"ADM_CLINICA"}),
    "profesionales, escritura (RF4)": (profesionales.admin_de_clinica, {"ADM_CLINICA"}),
    "pacientes, lectura (RF14)": (pacientes.quien_lee, {"ADM_CLINICA", "RECEPCION", "PROFESIONAL"}),
    "pacientes, escritura (RF14)": (pacientes.quien_escribe, {"ADM_CLINICA", "RECEPCION"}),
    "nota clínica (RF15)": (notas.solo_profesional, {"PROFESIONAL"}),
}


@pytest.mark.parametrize("fila", MATRIZ)
@pytest.mark.parametrize("rol", ROLES)
def test_cada_filtro_deja_pasar_solo_a_los_roles_de_la_matriz(fila, rol):
    filtro, permitidos = MATRIZ[fila]
    if rol in permitidos:
        s = sesion(rol)
        assert filtro(s) is s
    else:
        assert codigo_de(filtro, sesion(rol)) == 403


def test_leer_el_catalogo_lo_puede_cualquier_rol_con_clinica():
    """Quien no tiene clínica (plataforma) ya lo frena `sesion_de_clinica`, antes de llegar aquí."""
    for rol in ROLES:
        assert catalogo.lee_catalogo(sesion(rol)).rol == rol


def test_un_rol_desconocido_no_pasa_por_ningun_filtro():
    """Fallar cerrado: un rol que la matriz no conoce no hereda permisos."""
    for filtro, _ in MATRIZ.values():
        assert codigo_de(filtro, sesion("ROL_NUEVO")) == 403


def test_solo_el_profesional_escribe_notas_ni_siquiera_el_administrador():
    assert codigo_de(notas.solo_profesional, sesion("ADM_CLINICA")) == 403


# ---------- RF18: qué queda en la bitácora y qué no ----------

def auditorias(con):
    return con.escrituras("registro_auditoria")


def registro(con):
    """La única inserción en la bitácora: (clinica, usuario, paciente, accion)."""
    (sql, params), = auditorias(con)
    assert sql.startswith("INSERT INTO registro_auditoria")
    return params


PACIENTE_FILA = {"id": PACIENTE, "identificacion": "123", "nombre": "Ana", "fecha_nacimiento": date(1990, 1, 1), "telefono": None, "correo": None}


def datos_paciente(**cambios):
    return DatosPaciente(**{"identificacion": "123456", "nombre": "Ana Solís", "fecha_nacimiento": date(1990, 1, 1), **cambios})


def test_leer_la_ficha_de_un_paciente_queda_en_la_bitacora_con_quien_cual_y_que():
    con = ConexionFalsa([PACIENTE_FILA])
    pacientes.ver_paciente(PACIENTE, sesion("RECEPCION"), con)
    assert registro(con) == (CLINICA, USUARIO, PACIENTE, "LECTURA")
    assert "'CONTACTO_PACIENTE'" in auditorias(con)[0][0]


def test_buscar_un_paciente_que_no_existe_es_404_y_no_deja_registro():
    con = ConexionFalsa([None])
    assert codigo_de(pacientes.ver_paciente, PACIENTE, sesion(), con) == 404
    assert auditorias(con) == []


def test_registrar_un_paciente_queda_como_escritura_sobre_el_paciente_nuevo():
    nuevo = {**PACIENTE_FILA, "id": uuid.uuid4()}
    con = ConexionFalsa([None, nuevo])                    # no existía la identificación; el INSERT devuelve la fila
    pacientes.registrar_paciente(datos_paciente(), sesion("RECEPCION"), con)
    assert registro(con) == (CLINICA, USUARIO, nuevo["id"], "ESCRITURA")


def test_registrar_un_paciente_repetido_es_409_y_no_deja_registro_ni_inserta():
    con = ConexionFalsa([{"?column?": 1}])                # la identificación ya existe en la clínica
    assert codigo_de(pacientes.registrar_paciente, datos_paciente(), sesion(), con) == 409
    assert con.escrituras() == []


def test_actualizar_un_paciente_queda_como_escritura():
    con = ConexionFalsa([None, PACIENTE_FILA])
    pacientes.actualizar_paciente(PACIENTE, datos_paciente(), sesion(), con)
    assert registro(con) == (CLINICA, USUARIO, PACIENTE, "ESCRITURA")


def test_actualizar_un_paciente_de_otra_clinica_es_404_y_no_deja_registro():
    con = ConexionFalsa([None, None])                     # no hay duplicado y el UPDATE no encontró fila en ESTA clínica
    assert codigo_de(pacientes.actualizar_paciente, PACIENTE, datos_paciente(), sesion(), con) == 404
    assert auditorias(con) == []


def test_listar_pacientes_y_ver_el_historial_no_se_auditan_porque_no_traen_contacto_ni_notas():
    pacientes.listar_pacientes("", sesion(), ConexionFalsa([{"n": 0}, []]))
    con = ConexionFalsa([{"?column?": 1}, []])
    pacientes.historial(PACIENTE, sesion(), con)
    assert con.escrituras() == []


NOTA = {"id": uuid.uuid4(), "cita_id": CITA, "contenido": "Dolor", "creada_en": None, "actualizada_en": None}
CITA_PROPIA = {"id": CITA, "paciente_id": PACIENTE, "estado": "ATENDIDA"}


def test_leer_una_nota_queda_como_lectura_del_paciente_de_esa_cita():
    con = ConexionFalsa([CITA_PROPIA, NOTA])
    notas.ver_nota(CITA, sesion("PROFESIONAL"), con)
    assert registro(con) == (CLINICA, USUARIO, PACIENTE, "LECTURA")
    assert "'NOTA_CLINICA'" in auditorias(con)[0][0]


def test_escribir_una_nota_queda_como_escritura():
    con = ConexionFalsa([CITA_PROPIA, NOTA])
    notas.guardar_nota(CITA, DatosNota(contenido="Dolor"), sesion("PROFESIONAL"), con)
    assert registro(con) == (CLINICA, USUARIO, PACIENTE, "ESCRITURA")


def test_leer_una_nota_que_no_existe_es_404_y_no_deja_registro():
    con = ConexionFalsa([CITA_PROPIA, None])
    assert codigo_de(notas.ver_nota, CITA, sesion("PROFESIONAL"), con) == 404
    assert auditorias(con) == []


@pytest.mark.parametrize("estado", ["RESERVADA", "AUSENTE", "CANCELADA", "REPROGRAMADA"])
def test_solo_se_escribe_una_nota_sobre_una_cita_atendida_RF15(estado):
    con = ConexionFalsa([{**CITA_PROPIA, "estado": estado}])
    assert codigo_de(notas.guardar_nota, CITA, DatosNota(contenido="x"), sesion("PROFESIONAL"), con) == 409
    assert con.escrituras() == []


def test_una_cita_de_otro_profesional_u_otra_clinica_es_404_y_no_se_escribe_ni_audita():
    con = ConexionFalsa([None])
    assert codigo_de(notas.guardar_nota, CITA, DatosNota(contenido="x"), sesion("PROFESIONAL"), con) == 404
    assert con.escrituras() == []


# ---------- I5: la clínica (y en las notas, el profesional) salen de la sesión ----------

def test_la_cita_de_la_nota_se_busca_con_la_clinica_y_el_usuario_de_la_sesion():
    con = ConexionFalsa([CITA_PROPIA, NOTA])
    notas.ver_nota(CITA, sesion("PROFESIONAL"), con)
    (_, params), *_ = con.consultas
    assert params == (CITA, CLINICA, USUARIO)


def test_ver_un_paciente_filtra_por_la_clinica_de_la_sesion():
    con = ConexionFalsa([PACIENTE_FILA])
    pacientes.ver_paciente(PACIENTE, sesion(), con)
    assert con.consultas[0][1] == (PACIENTE, CLINICA)


def test_el_listado_de_pacientes_filtra_por_la_clinica_y_escapa_los_comodines():
    con = ConexionFalsa([{"n": 0}, []])
    pacientes.listar_pacientes(" 5%_ ", sesion(), con)
    for _, params in con.consultas:
        assert params == (CLINICA, "%5\\%\\_%", "%5\\%\\_%")


def test_el_texto_buscado_nunca_se_interpola_en_el_sql():
    malo = "'; DROP TABLE paciente; --"
    con = ConexionFalsa([{"n": 0}, []])
    pacientes.listar_pacientes(malo, sesion(), con)
    assert all("DROP" not in sql for sql, _ in con.consultas)


def test_el_historial_de_otra_clinica_es_404():
    con = ConexionFalsa([None])
    assert codigo_de(pacientes.historial, PACIENTE, sesion(), con) == 404
    assert len(con.consultas) == 1 and con.consultas[0][1] == (PACIENTE, CLINICA)


# ---------- Validación de lo que entra (esquemas) ----------

@pytest.mark.parametrize("campo", ["clinica_id", "id", "creada_por"])
def test_paciente_y_nota_rechazan_campos_que_decide_el_servidor(campo):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        datos_paciente(**{campo: str(uuid.uuid4())})
    with pytest.raises(ValidationError):
        DatosNota(contenido="x", **{campo: str(uuid.uuid4())})


@pytest.mark.parametrize("contenido", ["", "   "])
def test_una_nota_vacia_o_de_espacios_se_rechaza(contenido):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DatosNota(contenido=contenido)
