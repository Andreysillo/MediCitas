"""Medición de la caché de RF7 (T34): lo mismo con y sin Redis. No es una prueba: pytest no lo recoge.

Levanta DOS copias de la API de agenda como procesos aparte (uvicorn, un solo proceso cada una): una sin Redis y otra
con él. Entre un escenario y otro solo cambia eso; la base, los datos y el código son los mismos. Los clientes corren en
este proceso, y el servidor en otro: si compartieran proceso se disputarían el mismo GIL de Python y se mediría al
cliente, no a la API.

    docker compose --profile pruebas run --rm pruebas-agenda python -m tests.medir_cache

Mejor sobre una base con volumen (db/pruebas/historial_sintetico.sql). Escenarios de RF7:
  sin caché         cada consulta se calcula en PostgreSQL.
  caché, copia      la copia ya está guardada: se validan servicio y profesional en la base, y se lee de Redis.
  caché, sin copia  justo después de una invalidación: Redis no tiene la copia, así que se calcula y se guarda.
La comparación en paralelo reparte las solicitudes entre varios clientes a la vez. No sustituye una prueba de carga
(Etapa 2): solo muestra si la caché ayuda cuando hay concurrencia.
"""

import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import date, timedelta

import httpx
import psycopg
import redis
from psycopg.rows import dict_row

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
SECUENCIALES = 300
CLIENTES, POR_CLIENTE = 16, 60


@contextmanager
def api(con_redis: bool):
    """Una API de agenda en su propio proceso, con sesión de desarrollo y logs apagados. Devuelve su URL."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    entorno = {**os.environ, "AUTH_MODO": "desarrollo", "NIVEL_LOG": "WARNING"}
    entorno.pop("REDIS_URL", None)
    if con_redis:
        entorno["REDIS_URL"] = REDIS_URL
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(puerto),
         "--log-level", "warning", "--no-access-log"], env=entorno, stdout=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{puerto}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{url}/salud", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("la API no arrancó")
        yield url
    finally:
        proceso.terminate()
        proceso.wait(10)


def resumen(ms: list[float]) -> str:
    ms = sorted(ms)
    return f"mediana {statistics.median(ms):6.2f} ms · p95 {ms[int(len(ms) * 0.95)]:6.2f} ms"


def main() -> None:
    bd = psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True)
    laura = bd.execute(
        """SELECT p.id AS profesional, ps.servicio_id AS servicio,
                  (SELECT u.id FROM usuario u JOIN rol r ON r.id = u.rol_id
                    WHERE u.clinica_id = p.clinica_id AND r.codigo = 'RECEPCION' LIMIT 1) AS recepcion
             FROM profesional p JOIN usuario u ON u.id = p.usuario_id
             JOIN profesional_servicio ps ON ps.profesional_id = p.id
            WHERE u.nombre LIKE '%Laura%' ORDER BY ps.servicio_id LIMIT 1""").fetchone()
    lunes = date.today() + timedelta(days=7)
    while lunes.isoweekday() != 1:
        lunes += timedelta(days=1)
    ruta = f"/profesionales/{laura['profesional']}/disponibilidad"
    params = {"servicio_id": str(laura["servicio"]), "fecha": lunes.isoformat()}
    cabecera = {"X-Usuario-Id": str(laura["recepcion"])}
    version = f"disp:version:{laura['profesional']}"
    volumen = bd.execute("SELECT (SELECT count(*) FROM cita) AS citas, (SELECT count(*) FROM bloqueo_agenda) AS bloqueos").fetchone()
    indices = [r["indexrelname"] for r in bd.execute(
        "SELECT indexrelname FROM pg_stat_user_indexes WHERE indexrelname IN ('bloqueo_por_profesional_y_rango', 'cita_reservadas_por_profesional')")]
    print(f"Volumen: {volumen['citas']} citas, {volumen['bloqueos']} bloqueos · índices de T15: {len(indices)} de 2")
    en_redis = redis.Redis.from_url(REDIS_URL)
    en_redis.delete(*en_redis.keys("disp:*") or ["disp:nada"])     # arranca con la caché vacía

    with api(False) as url_sin, api(True) as url_con:
        def consultar(url: str, cliente: httpx.Client) -> float:
            t = time.perf_counter()
            r = cliente.get(url + ruta, params=params, headers=cabecera)
            assert r.status_code == 200, r.text
            return (time.perf_counter() - t) * 1000

        def en_paralelo(url: str) -> tuple[float, list[float]]:
            """CLIENTES hilos, cada uno con su conexión, hacen POR_CLIENTE solicitudes. Devuelve (solicitudes/s, tiempos)."""
            tiempos, barrera = [], threading.Barrier(CLIENTES + 1)

            def cliente():
                with httpx.Client(timeout=60) as c:
                    consultar(url, c)                      # abre la conexión antes de empezar a contar
                    barrera.wait()
                    tiempos.extend(consultar(url, c) for _ in range(POR_CLIENTE))

            hilos = [threading.Thread(target=cliente) for _ in range(CLIENTES)]
            for h in hilos:
                h.start()
            barrera.wait()
            inicio = time.perf_counter()
            for h in hilos:
                h.join()
            return CLIENTES * POR_CLIENTE / (time.perf_counter() - inicio), tiempos

        with httpx.Client(timeout=60) as http:
            for url in (url_sin, url_con):                 # calentamiento: conexiones del pool, planes, imports
                for _ in range(30):
                    consultar(url, http)

            print(f"\n== Secuencial, {SECUENCIALES} solicitudes de RF7 (un cliente)")
            piso = []
            for _ in range(SECUENCIALES):                  # referencia: una ruta que no toca la base ni la sesión
                t0 = time.perf_counter()
                http.get(url_sin + "/salud")
                piso.append((time.perf_counter() - t0) * 1000)
            print(f"   referencia /salud  {resumen(piso)}   (el piso: uvicorn y FastAPI, sin base de datos)")
            sin = [consultar(url_sin, http) for _ in range(SECUENCIALES)]
            print(f"   sin caché          {resumen(sin)}")
            con = [consultar(url_con, http) for _ in range(SECUENCIALES)]
            print(f"   caché, copia       {resumen(con)}")
            sin_copia = []
            for _ in range(SECUENCIALES):
                en_redis.incr(version)                     # lo que haría una reserva: las copias anteriores dejan de servir
                sin_copia.append(consultar(url_con, http))
            print(f"   caché, sin copia   {resumen(sin_copia)}")

        print(f"\n== En paralelo, {CLIENTES} clientes × {POR_CLIENTE} solicitudes")
        rps_sin, t_sin = en_paralelo(url_sin)
        print(f"   sin caché          {rps_sin:6.0f} solicitudes/s · {resumen(t_sin)}")
        rps_con, t_con = en_paralelo(url_con)
        print(f"   caché, copia       {rps_con:6.0f} solicitudes/s · {resumen(t_con)}")

    print("\n== Resultado")
    print(f"   copia contra sin caché: {statistics.median(sin) / statistics.median(con):.2f}× en latencia (secuencial), "
          f"{rps_con / rps_sin:.2f}× en solicitudes por segundo (paralelo)")
    print(f"   sin copia contra sin caché: {statistics.median(sin_copia) - statistics.median(sin):+.2f} ms en la mediana "
          "(lo que cuesta intentar la caché y fallar)")


if __name__ == "__main__":
    main()
