"""T30: las invariantes I3 e I6, con una prueba que las nombra.

I3. Una cita solo se reserva dentro del horario del profesional y fuera de sus bloqueos, validado DENTRO de la transacción de
la reserva. Además de lo de este archivo, I3 lo prueban:
  - test_reserva.py        fuera del horario, bloques partidos, bordes exactos y bloqueos (test_fuera_del_horario_I3, test_bloqueo_I3)
  - test_ciclo_de_vida.py  reprogramar respeta horario y bloqueos
  - test_horarios.py       quitar un bloque lista las reservas que quedan fuera
  - test_concurrencia.py   un bloqueo, o quitar un bloque, a la vez que una reserva (dos pruebas)
  - unitarias/             el orden de los bloqueos y los mensajes de cada regla

I6. La bitácora no admite modificación ni borrado por parte de la aplicación, impuesto por el MOTOR, no por convención. Son dos
barreras:
  - el TRIGGER (migración 010_bitacora): rechaza UPDATE, DELETE y TRUNCATE sea quien sea, dueño y superusuario incluidos.
  - los PRIVILEGIOS de los roles de los servicios (migración 011_roles, T19): sin UPDATE, DELETE ni TRUNCATE, y sin ser dueños
    de la tabla ni superusuarios.
"""

from datetime import date, datetime, timedelta, timezone

import psycopg
import pytest
from conftest import como, poner_horario, proximo

UTC = timezone.utc


def reservar(cliente, mundo, inicio, paciente=None):
    return cliente.post("/citas", headers=como(mundo.recepcion), json={
        "paciente_id": str(paciente or mundo.paciente), "profesional_id": str(mundo.prof),
        "servicio_id": str(mundo.servicio), "inicio": inicio.isoformat()})


def cabe(con, mundo, inicio, fin) -> bool:
    return con.execute("SELECT cabe_en_horario(%s, %s, %s) AS cabe", (mundo.prof, inicio, fin)).fetchone()["cabe"]


# ---------- I3: RF7 y RF9 hablan de la misma hora ----------
# La disponibilidad (espacios.py) y la reserva (cabe_en_horario, migración 006) convierten la hora local de la clínica a un
# instante por caminos DISTINTOS. Si algún día discreparan, la pantalla ofrecería horas que luego se rechazan, o al revés.
# Los instantes esperados están escritos a mano, para no depender de la misma biblioteca de zonas horarias que se prueba.

ZONAS = [
    # zona, día (siempre se atiende de 08:00 a 12:00 hora local), instante UTC al que corresponden las 08:00 locales
    ("America/Costa_Rica", date(2030, 1, 7), datetime(2030, 1, 7, 14, tzinfo=UTC)),    # UTC-6 todo el año
    ("America/New_York", date(2030, 3, 3), datetime(2030, 3, 3, 13, tzinfo=UTC)),      # domingo antes del cambio: UTC-5
    ("America/New_York", date(2030, 3, 10), datetime(2030, 3, 10, 12, tzinfo=UTC)),    # domingo del cambio a horario de verano: UTC-4
    ("America/New_York", date(2030, 11, 3), datetime(2030, 11, 3, 13, tzinfo=UTC)),    # domingo del regreso al horario normal: UTC-5
]


@pytest.mark.parametrize("zona, dia, apertura", ZONAS, ids=["costa_rica", "nueva_york_antes_del_cambio", "nueva_york_cambio_a_verano", "nueva_york_cambio_a_invierno"])
def test_lo_que_RF7_ofrece_lo_acepta_RF9_y_lo_de_al_lado_no_I3(cliente, mundo, con, zona, dia, apertura):
    con.execute("UPDATE clinica SET zona_horaria = %s WHERE id = %s", (zona, mundo.clinica_a))
    poner_horario(con, mundo, mundo.prof, dia.isoweekday(), "08:00", "12:00")
    treinta, cierre = timedelta(minutes=30), apertura + timedelta(hours=4)

    r = cliente.get(f"/profesionales/{mundo.prof}/disponibilidad", headers=como(mundo.recepcion),
                    params={"servicio_id": str(mundo.servicio), "fecha": dia.isoformat()})
    ofrecidos = [datetime.fromisoformat(e) for e in r.json()["espacios"]]

    # RF7: de las 08:00 a las 11:30 hora local, un inicio cada 15 minutos (la cita de 30 minutos tiene que terminar a las 12:00).
    assert ofrecidos[0] == apertura and ofrecidos[-1] == cierre - treinta and len(ofrecidos) == 15
    # RF9: todo lo que RF7 ofrece cabe en el horario, y un cuarto de hora antes de abrir o de cerrar ya no.
    assert all(cabe(con, mundo, inicio, inicio + treinta) for inicio in ofrecidos)
    fuera = [apertura - timedelta(minutes=15), cierre - timedelta(minutes=15)]
    assert not any(cabe(con, mundo, inicio, inicio + treinta) for inicio in fuera)
    # Y de punta a punta, por la API: las puntas se reservan, lo de al lado se rechaza.
    assert reservar(cliente, mundo, ofrecidos[0]).status_code == 201
    assert reservar(cliente, mundo, ofrecidos[-1], paciente=mundo.nuevo_paciente()).status_code == 201
    for inicio in fuera:
        r = reservar(cliente, mundo, inicio, paciente=mundo.nuevo_paciente())
        assert r.status_code == 422 and "fuera de la atención" in r.json()["detalle"], inicio


def test_una_cita_que_cruza_la_medianoche_no_cabe_aunque_las_horas_lo_parezcan_I3(cliente, mundo, con):
    """23:45 a 00:15 con un bloque de 20:00 a 23:59. Comparando solo las horas (23:45 >= 20:00 y 00:15 <= 23:59) pasaría;
    lo impide que `cabe_en_horario` exija que la cita empiece y termine el mismo día local."""
    poner_horario(con, mundo, mundo.prof, 1, "20:00", "23:59")
    r = reservar(cliente, mundo, proximo(1, 23, 45))
    assert r.status_code == 422 and "fuera de la atención" in r.json()["detalle"]
    assert reservar(cliente, mundo, proximo(1, 23, 15)).status_code == 201       # 23:15 a 23:45 sí cabe


# ---------- I6: la bitácora es append-only, en el motor ----------

# El motor rechaza con un privilegio que falta o con un trigger; los dos salen como insufficient_privilege (42501).
RECHAZOS = (psycopg.errors.InsufficientPrivilege,)


def bitacora(con, mundo) -> int:
    return con.execute(
        """INSERT INTO registro_auditoria (clinica_id, usuario_id, paciente_id, accion, recurso)
           VALUES (%s, %s, %s, 'LECTURA', 'NOTA_CLINICA') RETURNING id""",
        (mundo.clinica_a, mundo.admin, mundo.paciente)).fetchone()["id"]


def test_la_bitacora_sigue_admitiendo_filas_nuevas_I6(con, mundo):
    """Append-only no es solo-lectura: la protección no puede impedir que se escriba."""
    fila = bitacora(con, mundo)
    assert con.execute("SELECT count(*) AS n FROM registro_auditoria WHERE id = %s", (fila,)).fetchone()["n"] == 1


@pytest.mark.parametrize("sentencia", [
    "UPDATE registro_auditoria SET accion = 'ESCRITURA' WHERE id = {fila}",
    "UPDATE registro_auditoria SET ocurrido_en = ocurrido_en - interval '1 day' WHERE id = {fila}",     # reescribir la fecha
    "DELETE FROM registro_auditoria WHERE id = {fila}",
    "TRUNCATE registro_auditoria",
    "TRUNCATE usuario CASCADE",                    # vaciar una tabla a la que apunta arrastra a la bitácora: el trigger también salta
], ids=["update", "update_de_la_fecha", "delete", "truncate", "truncate_en_cascada"])
def test_el_motor_rechaza_modificar_o_borrar_la_bitacora_I6(con, mundo, sentencia):
    """Con la conexión del dueño de la tabla (superusuario): solo el trigger de la migración 010_bitacora la frena, porque
    un privilegio revocado no detiene al dueño. Los roles de los servicios, que no son dueños, los cubre la prueba de abajo."""
    fila = bitacora(con, mundo)
    with pytest.raises(RECHAZOS):
        with con.transaction():                     # punto de guardado: tras el error la prueba puede seguir consultando
            con.execute(sentencia.format(fila=fila))
    assert con.execute("SELECT accion FROM registro_auditoria WHERE id = %s", (fila,)).fetchone()["accion"] == "LECTURA"


def test_ningun_rol_de_la_aplicacion_puede_modificar_ni_borrar_la_bitacora_I6(con):
    """Los privilegios son la primera barrera, pero solo valen si la aplicación NO se conecta como superusuario ni como dueño."""
    roles = [r["rolname"] for r in con.execute("SELECT rolname FROM pg_roles WHERE rolcanlogin AND NOT rolsuper")]
    assert roles, "todos los servicios se conectan como superusuario: ningún privilegio los frena"
    for rol in roles:
        for privilegio in ("UPDATE", "DELETE", "TRUNCATE"):
            puede = con.execute("SELECT has_table_privilege(%s, 'registro_auditoria', %s) AS puede", (rol, privilegio)).fetchone()["puede"]
            assert not puede, f"el rol {rol} tiene {privilegio} sobre registro_auditoria"
