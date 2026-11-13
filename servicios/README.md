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

Todo pasa por `sesion_actual`, en [comun/medicitas_comun/sesion.py](comun/medicitas_comun/sesion.py). Una ruta no sabe
cómo se autenticó nadie: solo recibe el usuario, la clínica y el rol. Por eso agregar Keycloak no cambió ninguna ruta.

| `AUTH_MODO` | Quién dice la identidad | Dónde se usa |
|---|---|---|
| `keycloak` (por defecto) | Un JWT en `Authorization: Bearer ...` | El sistema real |
| `desarrollo` | La cabecera `X-Usuario-Id`, **sin validar: no es seguro** | Solo `pruebas-agenda` |
| Cualquier otro | Nadie: todo responde 401 | |

Con Keycloak, cada solicitud sigue estos pasos:

1. **Se valida el token:** la firma contra las llaves públicas del realm, el emisor, que no esté vencido y que sea un token
   de acceso (`typ: Bearer`). Un token que no pase responde 401.
2. **Se busca al usuario** por `keycloak_sub = sub` en la tabla `usuario`. De esa fila salen la clínica y el rol: la base es
   la fuente de verdad, no los roles que trae el token.
3. **Se revisa `activo`** en cada solicitud, así que una baja corta el acceso de inmediato (403), sin esperar a que el token
   venza.

Dos direcciones distintas, a propósito:

- `KEYCLOAK_ISSUER` es la dirección **pública** (`http://localhost:8080/auth/...`): el emisor escrito en el token, fijado con
  `KC_HOSTNAME` para que sea el mismo sin importar por dónde se pidió.
- `KEYCLOAK_JWKS_URL` es la dirección **interna** (`http://keycloak:8080/...`): de donde las APIs bajan las llaves.

Las llaves quedan en memoria. Si Keycloak se cae, los tokens ya emitidos siguen funcionando y no se pueden pedir nuevos. Si
además la API se reinicia y no tiene las llaves, responde 503, y se recupera sola cuando Keycloak vuelve.

Las pruebas de `pruebas-agenda` corren en modo `desarrollo`: comprueban las reglas de negocio, no el token. Las pruebas de
permisos con tokens reales son la tarea T29.

## Pruebas

Hay dos clases, y se distinguen por lo que necesitan para correr:

| | Unitarias (`tests/unitarias/`) | De integración (`tests/*.py`) |
|---|---|---|
| Qué prueban | La lógica propia del código: qué valida, en qué orden bloquea, qué invalida, cómo arma una consulta | La API contra la pila real: lo que decide el motor (solapes, claves foráneas, triggers), la concurrencia y la caché con Redis |
| Qué necesitan | **Nada**: ni base de datos ni Redis. Usan dobles (`tests/unitarias/dobles.py`) | Postgres con el esquema aplicado; las de caché, también Redis |
| Cuánto tardan | Menos de un segundo | Unos 15 segundos |

```bash
docker compose --profile pruebas run --rm --build pruebas-agenda                                    # las dos clases
docker compose --profile pruebas run --rm --no-deps pruebas-agenda python -m pytest tests/unitarias   # solo las unitarias, sin base
```

Cuál escribir: si lo que se decide lo decide el **código** (un orden, un rechazo, una invalidación), unitaria; si lo decide
el **motor** (que dos reservas simultáneas del mismo espacio terminen en un solo 201), integración, porque un doble no puede
reproducir al motor. El cálculo de los espacios libres es una consulta SQL, así que sus resultados también se prueban con
integración; las unitarias cubren lo que la rodea.

En las de integración, `tests/conftest.py` arma un "mundo" mínimo por prueba (dos clínicas, usuarios de cada rol,
profesionales, un paciente) y da `mundo.cita(...)` para crear citas. Casi todas se deshacen con ROLLBACK, así que no
dependen de la semilla ni dejan datos; las que necesitan datos confirmados (concurrencia y caché) borran lo que crean.

## Reglas entre servicios y tareas

- **Bloqueo de fila sobre el profesional (y el paciente).** Toda operación que cambie lo que el profesional puede
  atender o lo que tiene reservado toma `FOR NO KEY UPDATE` sobre su fila de `profesional`: un bloqueo nuevo, quitar un
  bloque de horario, reservar. La reserva toma además la del paciente, SIEMPRE en ese orden (profesional, luego
  paciente). Con eso nunca queda una cita dentro de un bloqueo sin que el sistema lo sepa (I3) y, sobre todo, no hay deadlocks entre reservas que
  disputan el mismo espacio: medido con 8 clientes y bloqueo compartido (`FOR SHARE`), varios abortaban con 40P01,
  porque Postgres inserta la entrada del índice de exclusión antes de revisarla y cada inserción veía la de la otra.
  La reprogramación usa el mismo camino: toma al profesional de destino y al paciente, y después la cita. El profesional
  de origen no hace falta: liberar un espacio no pone en riesgo nada.

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
