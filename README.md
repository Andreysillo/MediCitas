# MediCitas

## Levantar todo

Requisito: Docker con Compose.

```bash
cp .env.example .env          # y cambiar las contraseñas
docker compose up -d --build
docker compose ps             # todo "healthy"; migraciones "Exited (0)"
```

Abre http://localhost:8080. La documentación de cada API está en `/api/agenda/docs`, `/api/plataforma/docs`
y `/api/auditoria/docs`.

| Contenedor | Qué hace |
|---|---|
| `db` | PostgreSQL 16. Sin puerto publicado |
| `migraciones` | Aplica el esquema y la semilla nuevos, y termina ([db/](db/README.md)) |
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
docs/        enunciado y diseño del modelo lógico
```

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
