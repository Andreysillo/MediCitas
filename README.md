# MediCitas

## Levantar todo

Requisito: Docker con Compose.

```bash
cp .env.example .env          # y cambiar las contraseñas
docker compose up -d --build
docker compose ps             # todo "healthy"; migraciones "Exited (0)"
```

Abre http://localhost:8080. La documentación de cada API está en `/api/agenda/docs`, `/api/plataforma/docs`
y `/api/auditoria/docs`, y resumida, con roles y errores, en [docs/api.md](docs/api.md).

| Contenedor | Qué hace |
|---|---|
| `db` | PostgreSQL 16. Sin puerto publicado |
| `migraciones` | Aplica el esquema y la semilla nuevos, y termina ([db/](db/README.md)) |
| `keycloak` | Proveedor de identidad (RF17). Importa `keycloak/realm-export.json` al arrancar: nada se configura a mano |
| `redis` | Caché de la disponibilidad (RF7). Sin disco y sin puerto publicado: si se apaga, agenda sigue desde la base |
| `agenda`, `plataforma`, `auditoria` | Las tres APIs ([servicios/](servicios/README.md)) |
| `web` | El frontend compilado y el gateway hacia las APIs |

- `docker compose logs -f agenda`: logs en JSON de un servicio.
- `docker compose down`: apaga todo y conserva los datos. `down -v`: también borra la base.
- `docker compose --profile herramientas up -d`: agrega pgAdmin en http://localhost:5050.

## Estructura

```
frontend/    React + Vite; en Docker lo sirve nginx
servicios/   las tres APIs (FastAPI) y su infraestructura común
db/          migraciones, semilla y pruebas del esquema
docs/        enunciado, diseño del modelo lógico y referencia de la API
keycloak/        modulo keycloak para identidad y acceso (autenticación)
```

## Caché de disponibilidad (Redis)

RF7 (qué horas libres tiene un profesional) es la consulta que más veces se ejecuta, y calcularla en PostgreSQL cuesta.
Por eso se sirve desde Redis, que corre en el Compose sin disco y sin puerto publicado. **Redis solo guarda copias**: la verdad
siempre está en PostgreSQL, y si Redis se apaga, la agenda sigue funcionando desde la base, algo más lenta.

### Cómo pensarla: una pizarra con hojas

Imagina la recepción de la clínica:

- **La agenda oficial es PostgreSQL.** Siempre es correcta, pero contestar "¿qué horas libres tiene la Dra. Méndez el lunes?"
  obliga a revisar horarios, bloqueos y citas.
- **Redis es una pizarra con hojas ya resueltas**, por ejemplo: «Dra. Méndez · lunes 16 · Control de 15 min → libres 8:00, 8:15,
  8:30…». Leer una hoja es casi instantáneo.
- **Cada hoja es la copia de UNA consulta**. Su título es la *clave*: clínica, profesional, servicio, duración, fecha y un número
  de edición. Si cualquiera de esos datos cambia, el título es otro y se busca (o se crea) otra hoja.
- **Cada profesional tiene un letrero con su número de edición.** Reservar, cancelar, reprogramar o cambiar sus horarios o
  bloqueos sube el letrero (de 7 a 8). Las hojas de la edición 7 siguen en la pizarra, pero nadie las vuelve a buscar: todos
  piden la 8. Así, **un solo número invalida todas las fechas y servicios de ese profesional**, sin buscar hoja por hoja.
- **Un conserje tira cada hoja a los 5 minutos** (el *TTL*). No repone nada ni vuelve a una versión anterior: solo la tira, y la
  siguiente consulta la recalcula. Es una red de seguridad por si un letrero no llegó a subir; no es lo que mantiene correcta
  la caché.

Un ejemplo, con Ana y Beto que consultan, y Luis que reserva:

| Hora | Qué ocurre | Letrero | Hojas en la pizarra |
|---|---|---|---|
| 9:00 | Ana consulta el lunes 16. No hay hoja: se calcula en PostgreSQL y se cuelga la hoja | 7 | edición 7 |
| 9:01 | Beto consulta lo mismo: lee la hoja, sin calcular | 7 | edición 7 |
| 9:02 | Luis reserva las 8:00. Primero la cita queda **confirmada** en PostgreSQL; luego sube el letrero; recién entonces se le responde | 8 | edición 7 (invisible) |
| 9:03 | Ana vuelve a consultar: busca la edición 8, no hay hoja, calcula, ya no ve las 8:00 libres y cuelga la hoja nueva | 8 | edición 7, edición 8 |
| 9:05 | El conserje tira la hoja de la edición 7 | 8 | edición 8 |

Por eso la caché **no miente** (invariante I8): quien reserva nunca ve su espacio libre al volver a consultar, y no hay que
esperar a que venza nada. El orden importa: si el letrero subiera *antes* de confirmar la cita, alguien podría colgar una hoja
nueva sin ver todavía la reserva, y esa hoja falsa se quedaría.

Tres cosas que suelen confundirse:

1. **Cambiar la duración de un servicio no sube el letrero.** La duración está en el título de la hoja, así que las consultas
   piden hojas nuevas por su cuenta. Por eso `plataforma` puede editar servicios sin saber que existe Redis.
2. **Si la pizarra se llena,** Redis tira hojas primero y nunca letreros: si un letrero desapareciera, volvería a 0 y podrían
   reaparecer hojas viejas.
3. **Redis no guarda nada en disco, a propósito.** Al reiniciarse arranca con la pizarra vacía, y eso siempre es correcto. Un
   respaldo traería hojas que quizá ya no son verdad.

Con los índices de la base, una hoja ahorra unos 2 ms por consulta; sin ellos, más del doble
([medición](servicios/agenda/README.md#qué-se-midió-t34)). Todas las decisiones, la incoherencia que queda y por qué:
[servicios/agenda/README.md](servicios/agenda/README.md#caché-de-disponibilidad-rf7-i8).

## Identidad (Keycloak)

Las APIs no implementan login: lo hace Keycloak, que corre como contenedor más del compose. Su realm
(`medicitas`), roles, *clients* y usuarios de prueba se importan de
[keycloak/realm-export.json](keycloak/realm-export.json) al arrancar, sin pasos manuales. Consola de
administración: http://localhost:8080/auth/admin (usuario y contraseña de `KEYCLOAK_ADMIN*` en `.env`, no son
credenciales de la aplicación).

Los 18 usuarios de prueba son los mismos de la semilla de la base (su `id` en Keycloak es igual al
`keycloak_sub` que ya trae `db/seed/001_catalogos.sql`), con la contraseña **`medicitas123`**. Por ejemplo:

| Usuario (Keycloak) | Rol | Clínica |
|---|---|---|
| `plataforma` | ADM_PLATAFORMA | — |
| `san-rafael-admin` | ADM_CLINICA | Clínica San Rafael |
| `san-rafael-recepcion` | RECEPCION | Clínica San Rafael |
| `san-rafael-laura-mendez` | PROFESIONAL | Clínica San Rafael |

(y lo mismo para `del-valle-*` y `los-robles-*`; la lista completa está en el propio
`realm-export.json`).

Para pedir un token y llamar a la API (reemplaza `<usuario>`):

```bash
TOKEN=$(curl -s http://localhost:8080/auth/realms/medicitas/protocol/openid-connect/token \
  -d grant_type=password -d client_id=medicitas-api \
  -d username=<usuario> -d password=medicitas123 | jq -r .access_token)

curl -s http://localhost:8080/api/agenda/profesionales -H "Authorization: Bearer $TOKEN"
```

Con `san-rafael-admin` devuelve los profesionales de su clínica; sin token, 401; con `san-rafael-recepcion`, 403.

(`grant_type=password` es cómodo para pruebas y para la colección de peticiones; en un login real del
frontend sería *authorization code* + PKCE con el *client* `medicitas-web`, que el realm ya trae
configurado para cuando el frontend deje de usar datos en memoria.)

Cómo se asocia cada identidad con su clínica, y el resto de las decisiones de este módulo (por qué no se
valida `aud`, por qué el realm no persiste datos propios) están documentadas en
[docs/diseno-modelo-logico.md](docs/diseno-modelo-logico.md#10-identidad-delegada-keycloak).

## Decisiones de diseño

### Las citas no se solapan: lo garantiza el motor (I1 e I2)

Un `if` en el código no basta: si dos recepcionistas reservan el mismo espacio a la vez, ambas consultas ven
el espacio libre y las dos insertan. Por eso la regla vive en PostgreSQL, en
[db/migrations/004_citas.sql](db/migrations/004_citas.sql):

```sql
EXCLUDE USING gist (profesional_id WITH =, tstzrange(inicio, fin, '[)') WITH &&)
  WHERE (estado IN ('RESERVADA','ATENDIDA','AUSENTE'))
```

Se lee: "no puede haber dos citas del mismo profesional con rangos de tiempo que se traslapan, mirando solo
las que ocupan espacio".

- `'[)'` incluye el inicio y excluye el fin, así que 9:00–9:30 y 9:30–10:00 pueden convivir.
- El `WHERE` hace que cancelar o reprogramar libere el espacio sin borrar la cita (I7).
- Hay una exclusión gemela para el paciente (I2).
- Con concurrencia, la segunda transacción espera a la primera y, si chocan, falla con `23P01`; la API lo
  traduce a **409**.

### Una clínica nunca se mezcla con otra: claves foráneas compuestas (I5)

Cada tabla lleva `clinica_id`. Las claves foráneas incluyen la clínica: `cita (clinica_id, profesional_id)`
apunta a `profesional (clinica_id, id)`.

Con una clave simple, el motor solo comprobaría que el profesional exista, y una cita de la clínica A podría
quedar atada a un profesional de la B. Con la compuesta, el profesional debe ser de la **misma** clínica de la
cita; si no, el motor rechaza (`23503`, que la API traduce a 422).

Esto garantiza que **los datos son coherentes**, no **quién** puede verlos. De eso se encarga el token de
Keycloak, que dice la clínica del usuario, y el código que filtra por ella. Son dos capas: si el código se
equivoca, las claves compuestas impiden que los datos se mezclen.

### Migraciones: el mismo esquema en todos lados

[db/aplicar.sh](db/aplicar.sh) aplica los archivos de `db/migrations/` y `db/seed/` en orden, cada uno una
sola vez (lo anota en `schema_migrations`), completo o nada, y se detiene si algo falla. Lo corre el servicio
`migraciones` del compose antes de las APIs: así la base de cualquier entorno (la tuya, la del equipo, la del
servidor) llega al mismo esquema, y ninguna API arranca sobre uno incompleto. Un cambio nuevo es siempre la
migración siguiente; nunca se edita una ya aplicada.

### Servicios separados, no un monolito

`agenda`, `plataforma` y `auditoria` son contenedores distintos. Si uno cae, los demás siguen: sin `agenda`
no se puede reservar, pero sí gestionar pacientes o consultar la bitácora. El punto compartido es la base de
datos: si cae, las tres responden 503 hasta que vuelve. Además, cada persona edita su propia carpeta sin
pisar a la otra. Los servicios no se llaman entre sí, y cada tabla la escribe un solo servicio
([servicios/](servicios/README.md)).

### nginx: servidor del frontend y gateway

El contenedor `web` hace dos cosas: sirve los archivos del frontend y reenvía `/api/<servicio>/` al
contenedor que corresponde, así el navegador habla con un solo origen.

Por defecto nginx resuelve los nombres de sus destinos al arrancar y **se niega a iniciar** si alguno no
responde. Aquí el destino va en una variable ([frontend/nginx.conf](frontend/nginx.conf)), y se resuelve en
cada solicitud: la página arranca aunque una API esté caída, esa API responde 502 y las demás siguen. Cuando
vuelve, funciona sin reiniciar nada.

## Frontend en modo desarrollo

> El frontend todavía usa datos de prueba en memoria; cada función de `frontend/src/api/` se cambiará por un
> `fetch` a `/api/<servicio>/...`.

Requisito: Node.js 22 o superior.

```bash
cd frontend
npm install      # solo la primera vez o cuando cambie package.json
npm run dev      # abre http://localhost:5173
```

- La raíz (`#/`) es la landing promocional (producto ficticio). El logo de la barra lateral regresa a ella.
- **"Probar la demo"** abre el ingreso: se elige rol, clínica y usuario de prueba. Dentro solo aparece lo que ese rol puede ver, como pasará luego con el token de Keycloak. **"Cambiar de rol"** vuelve a esa pantalla y **"Salir"** regresa a la landing.
- Los cambios hechos en la página viven en memoria: al recargar vuelven los datos de prueba.
- `npm run build` verifica los tipos y compila. Conviene correrlo antes de hacer commit.
