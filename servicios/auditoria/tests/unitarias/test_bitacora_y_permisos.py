"""T33: unitarias de la bitácora (RF19), los reportes (RF21) y el permiso del servicio de auditoría, SIN base de datos.

Se llaman las funciones de las rutas directamente, con una conexión falsa que anota lo que se le pide. Lo que decide el
motor (que el filtro por clínica realmente aísle, que la bitácora no se pueda modificar) lo prueban las de integración.
"""

import inspect
import uuid
from datetime import date

import pytest
from conexion_falsa import ConexionFalsa
from fastapi import HTTPException

from app.bitacora import LIMITE, consultar_bitacora
from app.permisos import admin_de_clinica
from app.reportes import ESTADOS, MAX_DIAS, citas_por_estado
from medicitas_comun import Sesion

CLINICA, USUARIO = uuid.uuid4(), uuid.uuid4()
ADMIN = Sesion(USUARIO, CLINICA, "ADM_CLINICA")


def bitacora(con, *, usuario_id=None, paciente="", desde=None, hasta=None, sesion=ADMIN):
    return consultar_bitacora(usuario_id=usuario_id, paciente=paciente, desde=desde, hasta=hasta, sesion=sesion, con=con)


def con_resultados(total=0, filas=()):
    return ConexionFalsa([{"n": total}, list(filas)])


# ---------- Permiso (RF19: solo el administrador de la clínica) ----------

@pytest.mark.parametrize("rol", ["RECEPCION", "PROFESIONAL", "ADM_PLATAFORMA", "", "adm_clinica", "OTRO"])
def test_cualquier_rol_que_no_sea_administrador_de_clinica_recibe_403(rol):
    with pytest.raises(HTTPException) as e:
        admin_de_clinica(Sesion(USUARIO, CLINICA, rol))
    assert e.value.status_code == 403


def test_el_administrador_de_clinica_pasa_y_conserva_su_sesion():
    assert admin_de_clinica(ADMIN) is ADMIN


# ---------- Bitácora: filtros y armado de la consulta ----------

def test_la_clinica_de_la_consulta_es_la_de_la_sesion_y_la_ruta_no_recibe_otra_I5():
    con = con_resultados()
    bitacora(con)
    assert all(params["clinica"] == CLINICA for _, params in con.consultas)
    assert not {"clinica", "clinica_id", "tenant"} & set(inspect.signature(consultar_bitacora).parameters)


def test_se_hacen_dos_consultas_el_total_y_la_pagina_y_ambas_filtran_igual():
    con = con_resultados(total=250, filas=[{"id": 1}])
    r = bitacora(con, paciente="ana")
    assert r == {"total": 250, "registros": [{"id": 1}]}
    total, pagina = con.consultas
    assert total[1] == pagina[1]
    assert f"LIMIT {LIMITE}" in pagina[0] and "ORDER BY r.ocurrido_en DESC" in pagina[0]


@pytest.mark.parametrize("escrito, patron", [
    ("", "%%"),
    ("  Ana  ", "%Ana%"),
    ("50%", "%50\\%%"),
    ("a_b", "%a\\_b%"),
    ("a\\b", "%a\\\\b%"),
    ("%_\\", "%\\%\\_\\\\%"),
])
def test_los_comodines_del_texto_se_buscan_literalmente(escrito, patron):
    con = con_resultados()
    bitacora(con, paciente=escrito)
    assert con.consultas[0][1]["patron"] == patron


def test_lo_que_escribe_el_usuario_viaja_como_parametro_nunca_dentro_del_sql():
    malo = "x'); DROP TABLE registro_auditoria; --"
    con = con_resultados()
    bitacora(con, paciente=malo)
    assert all("DROP" not in sql and malo not in sql for sql, _ in con.consultas)
    assert "DROP TABLE" in con.consultas[0][1]["patron"]      # el texto viaja como dato (con el «_» escapado), no como SQL


def test_los_filtros_se_pasan_tal_cual_a_la_consulta():
    otro, d1, d2 = uuid.uuid4(), date(2030, 1, 1), date(2030, 1, 31)
    con = con_resultados()
    bitacora(con, usuario_id=otro, desde=d1, hasta=d2)
    p = con.consultas[0][1]
    assert (p["usuario"], p["desde"], p["hasta"]) == (otro, d1, d2)


def test_sin_filtros_los_parametros_opcionales_van_en_none():
    con = con_resultados()
    bitacora(con)
    p = con.consultas[0][1]
    assert (p["usuario"], p["desde"], p["hasta"]) == (None, None, None)


def test_un_rango_invertido_es_422_y_ni_siquiera_toca_la_base():
    con = con_resultados()
    with pytest.raises(HTTPException) as e:
        bitacora(con, desde=date(2030, 2, 1), hasta=date(2030, 1, 1))
    assert e.value.status_code == 422
    assert con.consultas == []


def test_desde_y_hasta_el_mismo_dia_es_un_rango_valido():
    assert bitacora(con_resultados(), desde=date(2030, 1, 1), hasta=date(2030, 1, 1)) == {"total": 0, "registros": []}


def test_con_solo_un_extremo_no_hay_rango_que_invertir():
    bitacora(con_resultados(), desde=date(2030, 1, 1))
    bitacora(con_resultados(), hasta=date(2000, 1, 1))


def test_consultar_la_bitacora_nunca_escribe_en_ella_I6():
    con = con_resultados()
    bitacora(con, paciente="ana", usuario_id=uuid.uuid4())
    assert con.escrituras() == []


def test_todos_los_joins_de_la_bitacora_llevan_la_clinica_I5():
    """Ningún JOIN debe poder cruzar de clínica: cada uno une también por clinica_id."""
    con = con_resultados()
    bitacora(con)
    sql = con.consultas[1][0]
    for tabla in ("usuario u", "paciente pa"):
        union = sql.split(f"JOIN {tabla}")[1].split("JOIN")[0]
        assert "clinica_id = r.clinica_id" in union, f"JOIN {tabla} sin la clínica"


# ---------- Reportes (RF21) ----------

def reporte(con, desde, hasta, sesion=ADMIN):
    return citas_por_estado(desde=desde, hasta=hasta, sesion=sesion, con=con)


def test_el_reporte_incluye_todos_los_estados_aunque_valgan_cero():
    r = reporte(ConexionFalsa([[]]), date(2030, 1, 1), date(2030, 1, 7))
    assert r["por_estado"] == dict.fromkeys(ESTADOS, 0)
    assert r["total"] == 0


def test_el_reporte_suma_el_total_y_respeta_el_conteo_de_cada_estado():
    filas = [{"estado": "ATENDIDA", "n": 5}, {"estado": "CANCELADA", "n": 2}]
    r = reporte(ConexionFalsa([filas]), date(2030, 1, 1), date(2030, 1, 7))
    assert r["por_estado"]["ATENDIDA"] == 5 and r["por_estado"]["CANCELADA"] == 2 and r["por_estado"]["RESERVADA"] == 0
    assert r["total"] == 7
    assert (r["desde"], r["hasta"]) == (date(2030, 1, 1), date(2030, 1, 7))


def test_el_reporte_cuenta_solo_la_clinica_de_la_sesion_con_una_sola_consulta():
    con = ConexionFalsa([[]])
    reporte(con, date(2030, 1, 1), date(2030, 1, 7))
    (sql, params), = con.consultas
    assert params == (CLINICA, date(2030, 1, 1), date(2030, 1, 7)) and "GROUP BY c.estado" in sql


@pytest.mark.parametrize("desde, hasta", [(date(2030, 1, 2), date(2030, 1, 1))])
def test_un_rango_invertido_en_el_reporte_es_422(desde, hasta):
    con = ConexionFalsa()
    with pytest.raises(HTTPException) as e:
        reporte(con, desde, hasta)
    assert e.value.status_code == 422 and con.consultas == []


def test_el_rango_maximo_son_366_dias_incluidos_y_uno_mas_es_422():
    inicio = date(2030, 1, 1)
    reporte(ConexionFalsa([[]]), inicio, date.fromordinal(inicio.toordinal() + MAX_DIAS - 1))        # 366 días: pasa
    with pytest.raises(HTTPException) as e:
        reporte(ConexionFalsa([[]]), inicio, date.fromordinal(inicio.toordinal() + MAX_DIAS))        # 367: no
    assert e.value.status_code == 422
