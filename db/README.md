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
| `005_auditoria.sql` | `registro_auditoria` (solo la tabla; la protección de I6 llega en 010) |
| `006_funciones_agenda.sql` | `cabe_en_horario()`: la única definición de "la cita cabe en el horario" (I3), usada por la reserva y por los conflictos de RF5 |
| `007_cita_protegida.sql` | Trigger `cita_protegida`: los estados finales no admiten salida (RF13) y los datos de una cita no se editan (I4) |
| `008_indices.sql` | Índices de bloqueos por profesional y rango, y de citas reservadas pendientes (T15; ver «Índices») |
| `009_indice_agenda_del_dia.sql` | Índice `cita (clinica_id, inicio)` para la agenda del día (RF20) y el conteo por estado (RF21) |
| `010_bitacora_solo_agregar.sql` | Trigger que rechaza `UPDATE`, `DELETE` y `TRUNCATE` sobre `registro_auditoria` (I6, primera barrera) |
| `011_roles.sql` | Roles `app_agenda`, `app_plataforma` y `app_auditoria` con sus permisos mínimos (T19, segunda barrera de I6); ver «Roles de base de datos» |

Reglas para cambiar el esquema:
- Un cambio nuevo es **la migración siguiente** (`008_...sql`). Nunca se edita una migración que ya se
  aplicó en alguna base: no se volvería a correr, y cada base quedaría distinta.
- Las migraciones solo van hacia adelante. Para deshacer algo se escribe otra migración que lo revierta.
- En una base vacía TODAS las migraciones corren antes que la semilla, así que la semilla debe respetar cualquier
  restricción nueva. Si una migración la rompe, se ajusta la semilla: ella sí se puede editar.

## Cómo se cargan

El servicio `migraciones` del compose corre `aplicar.sh` en cada `docker compose up`, después de que la
base está sana y antes de que arranquen las APIs. `aplicar.sh` anota cada archivo aplicado en la tabla
`schema_migrations` y corre cada uno en una sola transacción: con la base vacía crea todo, y con una base
existente aplica solo los archivos nuevos. Si uno falla, el servicio termina con error y las APIs no
arrancan.

`CARGAR_SEMILLA=no` (en `.env`) aplica solo el esquema, sin datos de prueba. Las fechas de la semilla son
relativas al momento en que se cargó: para refrescarlas, `docker compose down -v` y volver a levantar.

## Pruebas de restricciones

Arman sus propios datos y los deshacen al final, así que se pueden correr sobre la base con la semilla:

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/pruebas/restricciones.sql
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

## Índices

Medidos con volumen: la semilla más [pruebas/historial_sintetico.sql](pruebas/historial_sintetico.sql), que suma dos
años de historial (unas 83 mil citas) y 2 000 clínicas con 25 bloqueos cada una (50 mil). Así se ve un SaaS con
muchos clientes. El script es [servicios/agenda/tests/medir_consultas.py](../servicios/agenda/tests/medir_consultas.py),
y corre el mismo SQL que la API, 50 veces cada consulta:

```bash
docker compose exec -T db sh -c 'psql -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/pruebas/historial_sintetico.sql   # SOLO en una base de prueba
docker compose --profile pruebas run --rm pruebas-agenda python -m tests.medir_consultas          # agrega --plan para ver los planes
```

| Consulta | Antes | Después | Qué cambió |
|---|---|---|---|
| RF7: un profesional, un día | 4,39 ms | ~1,5 ms | `bloqueo_agenda` se leía entera; ahora usa `bloqueo_por_profesional_y_rango` |
| RF8: toda la clínica, 7 días | 25,0 ms | ~6 ms | El mismo índice, y la consulta descarta antes a quien no atiende el servicio |
| RF9: ¿la reserva cae en un bloqueo? | 2,66 ms | ~0,1 ms | `bloqueo_por_profesional_y_rango` |
| RF6: listar bloqueos | 3,88 ms | ~0,1 ms | Ídem |
| RF5 y RF6: citas reservadas en conflicto | 4,29 ms | ~0,65 ms | `cita_reservadas_por_profesional`: leía 6 867 citas para devolver 86 |
| RF2 (plataforma): pendientes al dar de baja | 2,25 ms | ~0,12 ms | Ídem |
| RF20 (B): la agenda de un día de una clínica | 126 ms | ~2,2 ms | `cita_por_clinica_e_inicio` (migración 009): `cita` se leía entera para filtrar por clínica y por día |

Medianas en la misma computadora; "antes" es el código y el esquema sin T15. Con solo la semilla (unas 2 000 citas) no hay
diferencia: RF7 tarda unos 1,6 ms y RF8 unos 14 ms con los dos códigos, porque con tablas chicas el motor prefiere leerlas
enteras, y acierta.

Lo que se decidió y por qué:

| Decisión | Razón |
|---|---|
| Ningún índice nuevo para las citas de RF7 y RF8 | Ya las sirve el GiST de la restricción de I1 (`cita_sin_solape_profesional`): misma expresión y mismo predicado. Otro índice sería redundante y haría más lentas las reservas |
| GiST, y no B-tree, para `bloqueo_agenda` | Las consultas usan `&&` entre rangos, que un B-tree no sirve. Es la misma expresión que en `cita` |
| Índice parcial `WHERE estado = 'RESERVADA'` | Una cita deja de estar reservada al resolverse, así que el índice guarda solo la agenda pendiente: 40 kB contra 10 MB del GiST de I1. No crece con el historial |
| La consulta de espacios no se prepara (`prepare=False`) | Preparada, Postgres puede pasarse a un plan genérico que no sabe si `profesional` es NULL y lee las tablas enteras. Medido forzándolo: RF7 de 1,2 a 99 ms y RF8 de 24 a 1 384 ms. Planificar cada vez cuesta alrededor de 1 ms |
| Profesionales habilitados en un CTE `MATERIALIZED` | Con muchas clínicas, el motor generaba los espacios de todos los profesionales y descartaba al final a quien no atiende el servicio: 1 120 búsquedas en vez de 280 |

Límites conocidos: `CREATE INDEX` bloquea las escrituras de la tabla mientras se construye, porque `aplicar.sh` corre cada
migración en una transacción. En producción, con tablas grandes, se usaría `CREATE INDEX CONCURRENTLY`, que no puede ir
dentro de una transacción. La consulta del historial del paciente y la de la bitácora de B quedan sin medir.

## Para quien escribe la lógica de las citas

- Un solape se rechaza con SQLSTATE `23P01` (I1 e I2) y una pareja profesional-servicio no habilitada con
  `23503`. La aplicación los traduce a 409 y 422.
- La exclusión se revisa fila por fila, no al final de la transacción. Al **reprogramar**, hay que marcar la
  cita antigua como `REPROGRAMADA` **antes** de insertar la nueva; si no, un horario que se solape con el
  viejo falla.
- `fin` se calcula con la duración del servicio dentro de la transacción de reserva (I4); el motor solo
  comprueba que `fin > inicio`.
- El motor no comprueba I3 (horario y bloqueos) ni que una nota sea de una cita ATENDIDA: son lógica de la
  aplicación. Las transiciones de estado sí tienen una segunda barrera en el motor (migración 007).

## Pendiente

Nada por ahora. Los roles de menor privilegio (T19) y la protección de la bitácora (I6) ya están; ver abajo.

## Roles de base de datos

Cada servicio se conecta con su propio rol (migración 011). Ninguno es superusuario ni dueño de las tablas; esas
siguen siendo de `POSTGRES_USER`, que solo usan las migraciones.

| Rol | Puede | No puede |
|---|---|---|
| `app_agenda` | Leer el catálogo; insertar y borrar horarios y bloqueos; insertar citas y cambiar su estado (solo las columnas de estado y cancelación) | Ver notas clínicas ni la bitácora; ver teléfono o correo de pacientes; editar datos de una cita |
| `app_plataforma` | Escribir clínicas, usuarios, catálogo, profesionales, pacientes y notas; **insertar** en la bitácora; leer citas | Modificar o borrar la bitácora; modificar citas |
| `app_auditoria` | Leer la bitácora y las columnas mínimas de clínica, paciente (nombre e identificación) y cita (fecha y estado) | Escribir en cualquier tabla; ver notas, teléfono o correo |

- La contraseña de cada rol sale del `.env` (`AGENDA_DB_PASSWORD`, `PLATAFORMA_DB_PASSWORD`, `AUDITORIA_DB_PASSWORD`).
  La migración crea los roles sin poder iniciar sesión, y `aplicar.sh` los habilita con la contraseña en cada arranque:
  una contraseña no debe vivir en un archivo versionado.
- **Dos barreras para I6.** Los roles no tienen `UPDATE`, `DELETE` ni `TRUNCATE` sobre `registro_auditoria`, y además los
  triggers de la migración 010 los rechazan aunque alguien se los diera por error. Un superusuario aún podría
  desactivar el trigger, por eso los servicios no se conectan como superusuario.
- **Una tabla o columna nueva no queda accesible sola.** La migración que la crea debe darle sus permisos a cada rol; si
  no, el servicio falla con `permission denied`. Las pruebas lo detectan: corren cada solicitud con el rol del servicio
  (`ROL_PRUEBAS` en el compose), y el resto (armar datos, comprobar) como superusuario.
- **Excepción documentada:** `SELECT ... FOR NO KEY UPDATE` exige `UPDATE` sobre al menos una columna. Para bloquear filas
  (reserva, bloqueos, usuarios), `app_agenda` y `app_plataforma` tienen `UPDATE (id)` sobre `profesional`, `paciente` y
  `clinica`, según el caso. Ninguna ruta cambia `id`, y el motor lo impediría mientras haya filas que lo referencien.
