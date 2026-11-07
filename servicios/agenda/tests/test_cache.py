"""Caché de RF7 (T14, I8), con Redis real, un servidor real y datos confirmados: la invalidación depende del COMMIT.

Para saber si una respuesta salió de la caché se cambia la base con SQL directo, sin pasar por la API. Si la respuesta no
cambia, vino de la copia guardada. Si después de una operación de la API sí cambia, esa operación invalidó.
"""

import os
import time
from datetime import timedelta

import httpx
import pytest
from conftest import como, poner_horario, proximo, servidor_real
from psycopg import connect
from psycopg.rows import dict_row

from app import cache
from app.main import app


@pytest.fixture(scope="module")
def url():
    with servidor_real(app) as u:
        yield u


class Agenda:
    """Un lunes de 08:00 a 10:00 para los dos profesionales, y una forma corta de consultar y de reservar."""

    def __init__(self, w, url):
        self.w = w
        self.sql = connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row)
        self.api = httpx.Client(base_url=url, headers=como(w.admin), timeout=10)
        for prof in (w.prof, w.prof2):
            poner_horario(self.sql, w, prof, 1, "08:00", "10:00")

    def parametros(self, **extra):
        return {"servicio_id": str(self.w.servicio), "fecha": proximo(1, 0).date().isoformat(), **extra}

    def libres(self, prof=None, **extra):
        r = self.api.get(f"/profesionales/{prof or self.w.prof}/disponibilidad", params=self.parametros(**extra))
        assert r.status_code == 200, r.text
        return r.json()["espacios"]

    def solicitar(self, inicio):
        paciente = self.sql.execute(
            """INSERT INTO paciente (clinica_id, identificacion, nombre, fecha_nacimiento)
               VALUES (%s, gen_random_uuid()::text, 'Paciente', '1990-01-01') RETURNING id""", (self.w.clinica_a,)).fetchone()["id"]
        return self.api.post("/citas", json={"paciente_id": str(paciente), "profesional_id": str(self.w.prof),
                                             "servicio_id": str(self.w.servicio), "inicio": inicio})

    def reservar(self, inicio):
        r = self.solicitar(inicio)
        assert r.status_code == 201, r.text
        return r.json()

    def cambiar_la_agenda_sin_avisar(self):
        """Un bloqueo escrito con SQL directo: la base cambia y la caché no se entera."""
        self.sql.execute("INSERT INTO bloqueo_agenda (clinica_id, profesional_id, inicio, fin, motivo) VALUES (%s,%s,%s,%s,'sql')",
                         (self.w.clinica_a, self.w.prof, proximo(1, 9), proximo(1, 9) + timedelta(minutes=30)))


@pytest.fixture
def agenda(mundo_real, url):
    a = Agenda(mundo_real, url)
    yield a
    a.api.close()
    a.sql.close()


def test_la_segunda_consulta_sale_de_la_copia(agenda):
    primera = agenda.libres()
    agenda.cambiar_la_agenda_sin_avisar()
    assert agenda.libres() == primera


def test_i8_reservar_y_volver_a_consultar_muestra_el_espacio_tomado(agenda):
    antes = agenda.libres()
    agenda.reservar(antes[0])
    assert antes[0] not in agenda.libres()


def test_cancelar_devuelve_el_espacio_de_inmediato(agenda):
    espacio = agenda.libres()[0]
    cita = agenda.reservar(espacio)
    assert espacio not in agenda.libres()
    assert agenda.api.post(f"/citas/{cita['id']}/cancelar", json={"motivo": "Prueba"}).status_code == 200
    assert espacio in agenda.libres()


def test_reprogramar_a_otro_profesional_invalida_las_dos_agendas(agenda):
    w = agenda.w
    espacio = agenda.libres()[0]
    cita = agenda.reservar(espacio)
    assert espacio not in agenda.libres() and espacio in agenda.libres(w.prof2)
    r = agenda.api.post(f"/citas/{cita['id']}/reprogramar", json={"profesional_id": str(w.prof2), "inicio": espacio})
    assert r.status_code == 201, r.text
    assert espacio in agenda.libres() and espacio not in agenda.libres(w.prof2)


def test_crear_y_quitar_un_bloqueo_invalida(agenda):
    espacio = agenda.libres()[0]
    inicio = proximo(1, 8)
    r = agenda.api.post(f"/profesionales/{agenda.w.prof}/bloqueos", json={
        "inicio": inicio.isoformat(), "fin": (inicio + timedelta(hours=1)).isoformat(), "motivo": "Permiso"})
    assert r.status_code == 201, r.text
    assert espacio not in agenda.libres()
    assert agenda.api.delete(f"/bloqueos/{r.json()['id']}").status_code == 204
    assert espacio in agenda.libres()


def test_agregar_y_quitar_un_horario_invalida(agenda):
    antes = len(agenda.libres())
    r = agenda.api.post(f"/profesionales/{agenda.w.prof}/horarios", json={"dia_semana": 1, "hora_inicio": "14:00", "hora_fin": "15:00"})
    assert r.status_code == 201, r.text
    assert len(agenda.libres()) > antes
    assert agenda.api.delete(f"/horarios/{r.json()['id']}").status_code == 200
    assert len(agenda.libres()) == antes


def test_una_reserva_rechazada_no_invalida(agenda):
    """Lo que corre tras el commit no corre si la solicitud falla: la copia sigue siendo válida."""
    espacio = agenda.libres()[0]
    agenda.reservar(espacio)
    primera = agenda.libres()
    agenda.cambiar_la_agenda_sin_avisar()
    assert agenda.solicitar(espacio).status_code == 409
    assert agenda.libres() == primera


def test_cambiar_la_duracion_del_servicio_no_necesita_invalidar(agenda):
    antes = agenda.libres()
    agenda.sql.execute("UPDATE servicio SET duracion_minutos = 60 WHERE id = %s", (agenda.w.servicio,))
    assert len(agenda.libres()) < len(antes)


def test_ignorar_cita_no_contamina_la_copia_de_los_demas(agenda):
    espacio = agenda.libres()[0]
    cita = agenda.reservar(espacio)
    assert espacio in agenda.libres(ignorar_cita=cita["id"])
    assert espacio not in agenda.libres()


def test_otra_clinica_no_alcanza_una_copia_guardada(agenda):
    agenda.libres()
    r = agenda.api.get(f"/profesionales/{agenda.w.prof}/disponibilidad", headers=como(agenda.w.admin_otra_clinica),
                       params=agenda.parametros())
    assert r.status_code == 404


def test_si_redis_no_responde_todo_sigue_funcionando_y_sin_demora(agenda, monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    cache._redis.cache_clear()
    try:
        inicio = time.perf_counter()
        espacio = agenda.libres()[0]                # la consulta se calcula en la base
        agenda.reservar(espacio)                    # 201: el INCR falló, pero la cita ya está guardada
        assert espacio not in agenda.libres()
        assert time.perf_counter() - inicio < 2
    finally:
        cache._redis.cache_clear()


# ---- La lógica de cache.espacios, sin pasar por las rutas ----

def consulta(w, calcular):
    return cache.espacios(w.clinica_a, w.prof, w.servicio, 30, proximo(1, 0).date(), calcular)


def test_una_copia_tardia_de_antes_de_invalidar_nadie_la_lee(mundo_real):
    """La carrera: la consulta ya leyó la base, alguien reserva e invalida, y recién entonces la consulta guarda."""
    w, viejo, nuevo = mundo_real, [proximo(1, 8)], []

    def calcular_mientras_alguien_reserva():
        cache._redis().incr(cache._clave_version(w.prof))
        return viejo

    assert consulta(w, calcular_mientras_alguien_reserva) == viejo
    assert consulta(w, lambda: nuevo) == nuevo


def test_las_horas_que_ya_pasaron_salen_de_la_copia(mundo_real):
    pasada, futura = proximo(1, 8).replace(year=2020), proximo(1, 8)
    assert consulta(mundo_real, lambda: [pasada, futura]) == [pasada, futura]
    assert consulta(mundo_real, lambda: pytest.fail("debía salir de la copia")) == [futura]


def test_redis_colgado_no_retrasa_mas_que_el_limite(mundo_real, monkeypatch):
    """Lo que pasa con el contenedor apagado: la resolución del nombre tarda segundos y el socket no la corta."""

    class Colgado:
        def get(self, clave):
            time.sleep(1)

    monkeypatch.setattr(cache, "_redis", lambda: Colgado())
    inicio = time.perf_counter()
    assert consulta(mundo_real, lambda: []) == []
    assert time.perf_counter() - inicio < 0.5


def test_las_copias_vencen_solas(mundo_real):
    consulta(mundo_real, lambda: [])
    r = cache._redis()
    claves = list(r.scan_iter(f"disp:{mundo_real.clinica_a}:*"))
    assert len(claves) == 1 and 0 < r.ttl(claves[0]) <= cache.TTL_SEGUNDOS
