# Base de datos

PostgreSQL 16. El esquema sigue [docs/diseno-modelo-logico.md](../docs/diseno-modelo-logico.md).

```
db/
  migrations/   esquema, un archivo por tema, en orden numérico
  seed/         datos de prueba, se aplican después de las migraciones
  pruebas/      pruebas SQL de las restricciones
  aplicar.sh    aplica migrations/ y seed/ una sola vez cada archivo
```

## Qué contiene cada migración

| Archivo | Contenido |
|---|---|
| `001_extensiones.sql` | `btree_gist` y el tipo `timerange` |
| `002_identidad.sql` | `clinica`, `rol` (datos fijos), `especialidad`, `usuario` |
| `003_agenda.sql` | `profesional`, `servicio`, `profesional_servicio`, `horario_atencion`, `bloqueo_agenda` |
| `004_citas.sql` | `paciente`, `cita` con las exclusiones de **I1** e **I2**, `nota_clinica` |
| `005_auditoria.sql` | `registro_auditoria` (solo la tabla; ver "Pendiente") |

Para agregar un cambio de esquema se crea la migración siguiente (`006_...sql`) y se vuelve a correr
`aplicar.sh`: solo aplica los archivos nuevos.

## Cómo se cargan

`aplicar.sh` anota cada archivo aplicado en la tabla `schema_migrations` y corre cada uno en una sola
transacción. El compose debe montar dos cosas en el servicio de Postgres:

```yaml
volumes:
  - ./db:/db:ro
  - ./db/aplicar.sh:/docker-entrypoint-initdb.d/aplicar.sh:ro
```

La imagen oficial ejecuta lo que hay en `docker-entrypoint-initdb.d/` solo en el primer arranque, con la
base vacía. Las fechas de la semilla son relativas al momento de ese arranque: para refrescarlas,
`docker compose down -v` y volver a levantar.

## Probar sin el compose completo

```bash
docker run -d --name medicitas-test -e POSTGRES_USER=medicitas -e POSTGRES_PASSWORD=x -e POSTGRES_DB=medicitas \
  -v "$PWD/db:/db:ro" -v "$PWD/db/aplicar.sh:/docker-entrypoint-initdb.d/aplicar.sh:ro" postgres:16

# Pruebas de restricciones (arman sus propios datos y los deshacen):
docker cp db/pruebas/restricciones.sql medicitas-test:/tmp/r.sql
docker exec medicitas-test psql -v ON_ERROR_STOP=1 -U medicitas -d medicitas -f /tmp/r.sql
```

## Datos semilla

3 clínicas, 18 usuarios, 11 profesionales con horarios (incluida una jornada partida), 16 servicios,
240 pacientes y unas 2000 citas entre 14 días antes y 14 días después de hoy, con los cinco estados,
reprogramaciones encadenadas por `cita_origen_id`, notas, bitácora y un bloqueo por clínica que cae sobre
citas ya reservadas (para ver los conflictos de RF6). Por construcción cumplen I1, I2, I3, I4, RF12 y RF15.

**Para Keycloak (persona B):** los ids salen de `md5('usuario:<clínica>:<clave>')::uuid` y
`usuario.keycloak_sub` es igual a `usuario.id`. El realm versionado debe crear cada usuario de prueba con
ese id como `sub`. Se obtienen con:

```sql
SELECT u.keycloak_sub, u.nombre, r.codigo AS rol, c.identificador AS clinica
  FROM usuario u JOIN rol r ON r.id = u.rol_id LEFT JOIN clinica c ON c.id = u.clinica_id;
```

## Para quien escribe la lógica de las citas

- Un solape se rechaza con SQLSTATE `23P01` (I1 e I2) y una pareja profesional-servicio no habilitada con
  `23503`. La aplicación los traduce a 409 y 422.
- La exclusión se revisa fila por fila, no al final de la transacción. Al **reprogramar**, hay que marcar la
  cita antigua como `REPROGRAMADA` **antes** de insertar la nueva; si no, un horario que se solape con el
  viejo falla.
- `fin` se calcula con la duración del servicio dentro de la transacción de reserva (I4); el motor solo
  comprueba que `fin > inicio`.
- El motor no comprueba I3 (horario y bloqueos), que una nota sea de una cita ATENDIDA, ni las transiciones
  de estado: son lógica de la reserva (RF9 a RF13).

## Pendiente

- Índices de la consulta de disponibilidad y su `EXPLAIN` (T15): migración `006`.
- Roles de base de datos con menor privilegio y la protección de `registro_auditoria` contra `UPDATE`,
  `DELETE` y `TRUNCATE` (I6), con trigger de respaldo (T19 y T23).
