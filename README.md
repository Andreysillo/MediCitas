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
