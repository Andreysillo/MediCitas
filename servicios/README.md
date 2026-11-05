# Servicios del backend

MediCitas no es un monolito: el backend son tres servicios de Python (FastAPI) que se despliegan, se caen y
se reinician por separado. Cada uno es dueño de un grupo de requisitos.

| Servicio | Responsable | Requisitos | Escribe en |
|---|---|---|---|
| `agenda` | Persona A | RF5–RF13, RF20 | `horario_atencion`, `bloqueo_agenda`, `cita` |
| `plataforma` | Persona B | RF1–RF4, RF14–RF16 | `clinica`, `usuario`, `especialidad`, `servicio`, `profesional`, `profesional_servicio`, `paciente`, `nota_clinica` |
| `auditoria` | Persona B | RF19, RF21 | nada: solo lee |

RF17 (autenticación con Keycloak) es común a los tres. RF18 (bitácora) lo cumple el servicio que lee o
escribe el dato protegido, con un `INSERT` en `registro_auditoria` **dentro de la misma transacción**. Si la
bitácora fuera una llamada HTTP a otro servicio, una caída de la red dejaría lecturas sin registrar.

## Cómo se comunican

- El navegador habla con un solo origen. El nginx del contenedor `web` reparte `/api/agenda/`,
  `/api/plataforma/` y `/api/auditoria/` hacia cada servicio ([frontend/nginx.conf](../frontend/nginx.conf)).
- Los servicios **no se llaman entre sí**. Comparten la base de datos, pero cada tabla tiene un solo
  servicio que escribe en ella (la tabla de arriba). Leer las tablas de otro está permitido, porque las
  restricciones del motor (I1, I2, I5) protegen la consistencia sin importar quién escriba. Cuando existan
  los roles de base de datos (T19), cada servicio tendrá su usuario, con permiso de escritura solo sobre
  sus tablas.

## Qué trae cada servicio sin escribir nada

Todo sale de `crear_app()` en [comun/medicitas_comun/app.py](comun/medicitas_comun/app.py):

- `GET /salud`: el proceso vive. `GET /listo`: además alcanza la base (lo usa el healthcheck de Docker).
- Un pool de conexiones que sobrevive a un reinicio de Postgres. La dependencia `conexion` da una
  conexión por solicitud dentro de una transacción: COMMIT si la ruta termina bien, ROLLBACK si falla.
- Los errores del motor se traducen solos: exclusión (I1, I2) y único → 409; clave foránea y CHECK → 422.
  La respuesta incluye la restricción violada. Base caída → 503. Cualquier otro error → 500 con el id de
  la solicitud, sin la traza (la traza queda en el log).
- Logs en JSON, una línea por solicitud, con el `solicitud` que también ve nginx (`X-Request-ID`).
- Documentación interactiva en `http://localhost:8080/api/<servicio>/docs`.

`comun/` es solo infraestructura. Una regla de negocio va en el servicio dueño del requisito, aunque otro
servicio la necesite parecida.

## Quién hace la solicitud

Una ruta que necesita saber quién llama recibe `sesion: Sesion = Depends(sesion_de_clinica)` y toma de ahí la
clínica y el rol. **La clínica nunca se lee de la solicitud** (I5).

Hoy, mientras no exista Keycloak, `AUTH_MODO=desarrollo` (compose) hace que la identidad llegue en la cabecera
`X-Usuario-Id`, sin validar: **no es seguro** y sirve solo para desarrollar. Con cualquier otro valor, todo
responde 401. Cuando B entregue la validación del JWT (T17 y T18), solo cambia el cuerpo de `sesion_actual`
en [comun/medicitas_comun/sesion.py](comun/medicitas_comun/sesion.py); las rutas no se tocan.

## Pruebas

Corren contra la base real y cada prueba se deshace con ROLLBACK, así que no dependen de la semilla ni dejan datos:

```bash
docker compose --profile pruebas run --rm --build pruebas-agenda
```

`tests/conftest.py` arma un "mundo" mínimo por prueba (dos clínicas, usuarios de cada rol, profesionales, un paciente)
y da `mundo.cita(...)` para crear citas.

## Reglas entre servicios y tareas

- **Bloqueo de fila sobre el profesional (y el paciente).** Toda operación que cambie lo que el profesional puede
  atender o lo que tiene reservado toma `FOR NO KEY UPDATE` sobre su fila de `profesional`: un bloqueo nuevo, quitar un
  bloque de horario, reservar. La reserva toma además la del paciente, SIEMPRE en ese orden (profesional, luego
  paciente). Con eso no se cuela una cita durante un bloqueo (I3) y, sobre todo, no hay deadlocks entre reservas que
  disputan el mismo espacio: medido con 8 clientes y bloqueo compartido (`FOR SHARE`), varios abortaban con 40P01,
  porque Postgres inserta la entrada del índice de exclusión antes de revisarla y cada inserción veía la de la otra.
  La reprogramación (T13) debe respetar el mismo orden; si toma dos profesionales, en orden de `id`.

## Agregar una ruta

En el servicio que corresponda, un archivo por grupo de requisitos, por ejemplo `agenda/app/disponibilidad.py`:

```python
from fastapi import APIRouter, Depends
from medicitas_comun import conexion

router = APIRouter(prefix="/disponibilidad", tags=["RF7"])

@router.get("/{profesional_id}")
def espacios(profesional_id: str, con=Depends(conexion)):
    return con.execute("SELECT ...", (profesional_id,)).fetchall()
```

y en `agenda/app/main.py`: `app.include_router(disponibilidad.router)`. Una dependencia nueva va en el
`requirements.txt` del servicio, con versión exacta.

## Correr un servicio fuera de Docker

```bash
cd servicios
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e comun -r agenda/requirements.txt
DATABASE_URL=postgresql://medicitas:<clave>@localhost:5432/medicitas uvicorn --app-dir agenda app.main:app --reload
```

La base del compose no publica su puerto. Para eso se agrega `ports: ["127.0.0.1:5433:5432"]` al
servicio `db` en un `compose.override.yml` propio, que no se versiona.
