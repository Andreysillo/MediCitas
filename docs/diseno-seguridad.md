# MediCitas, Etapa 1: diseño de seguridad (tenancy, identidad, roles de BD y bitácora)

Complementa [diseno-modelo-logico.md](diseno-modelo-logico.md), que cubre el modelo de datos, la 3FN, el diagrama
entidad-relación y el nivel de aislamiento transaccional. Aquí está lo demás del enunciado: la **comparación de estrategias de
multi-tenancy**, cómo se **asocia cada identidad con su clínica**, los **roles de base de datos** y la **bitácora**, cada uno
con sus alternativas, lo que se ganó y lo que se sacrificó.

| Sección | Enunciado | Invariantes y requisitos |
|---|---|---|
| [1. Multi-tenancy](#1-multi-tenancy) | Núcleo 2 | I5 |
| [2. Identidad delegada](#2-identidad-delegada-keycloak) | Núcleo 4 | RF17 |
| [3. Roles de base de datos](#3-roles-de-base-de-datos-con-menor-privilegio) | Núcleo 5 | I6, RF17 |
| [4. Bitácora de auditoría](#4-bitácora-de-auditoría) | Núcleo 5 | RF18, RF19, I6 |
| [5. Límites conocidos](#5-límites-conocidos-y-decisiones-pendientes) | | |

## 1. Multi-tenancy

El tenant es la clínica. **I5:** ningún dato de una clínica resulta accesible desde otra, por ninguna ruta ni combinación de
parámetros.

### 1.1 Estrategias comparadas

| | Esquema por tenant | Columna discriminadora (`clinica_id`) | Row-Level Security (RLS) |
|---|---|---|---|
| Idea | Un esquema de PostgreSQL por clínica, con las mismas tablas | Una sola copia de las tablas; cada fila lleva su `clinica_id` | Columna discriminadora más políticas del motor que filtran cada consulta según un valor de la sesión |
| Aislamiento de lecturas | Fuerte: la consulta ni ve las tablas de otra clínica | Lo hace el código: cada consulta debe filtrar por clínica | Lo hace el motor, aunque el código olvide el filtro |
| Aislamiento de escrituras (una fila que apunta a otra clínica) | Fuerte | Fuerte **si** las claves foráneas incluyen la clínica | Parcial: filtra lo que se ve, pero no impide por sí sola una referencia cruzada |
| Alta de una clínica | Crear un esquema y migrarlo (DDL en caliente) | Insertar una fila | Insertar una fila |
| Migraciones | Se aplican N veces, una por esquema; un fallo a medias deja clínicas con versiones distintas | Una vez | Una vez |
| Consultas entre clínicas (el administrador de plataforma lista las clínicas) | Difíciles: unir N esquemas | Triviales | Triviales, con una política aparte |
| Pool de conexiones | Cada solicitud debe fijar el `search_path` del tenant | Un solo pool | Cada solicitud debe fijar el valor de sesión, y un olvido o una conexión reutilizada con el valor anterior es una fuga |
| Complejidad operativa | Alta: catálogo del motor crece con las clínicas | Baja | Media: políticas por tabla y un contrato de sesión en todo el código |
| Pruebas | Casi todo lo hace la estructura | Hay que probar cada ruta | Hay que probar cada ruta y cada política |

### 1.2 Decisión: columna discriminadora con claves foráneas compuestas

Cada tabla de datos lleva `clinica_id`, y **las claves foráneas incluyen la clínica**. Por ejemplo, `cita (clinica_id,
profesional_id)` apunta a `profesional (clinica_id, id)`. Con una clave foránea simple el motor solo comprobaría que el
profesional exista, y una cita de la clínica A podría quedar atada a un profesional de la B. Con la compuesta, el motor
rechaza la fila (`23503`, que la API traduce a 422).

Por qué esta y no las otras:

- **Frente a esquema por tenant:** el producto es una plataforma que vende el servicio a muchas clínicas, y dar de alta una
  clínica (RF1) debe ser un `INSERT`, no un DDL. Con N esquemas, cada migración se aplica N veces y el administrador de
  plataforma, que lista todas las clínicas, tendría que unir esquemas. El costo de aislar es mucho mayor que el beneficio, porque
  los datos de una clínica nunca necesitan salir de su volumen ni de su versión de esquema.
- **Frente a RLS como única estrategia:** RLS filtra lo que se **ve**, pero no impide una **referencia** cruzada al escribir. Las
  claves foráneas compuestas sí. Además, RLS depende de que cada solicitud fije correctamente un valor de sesión sobre un pool de
  conexiones compartido: si una conexión vuelve al pool con el valor de otra clínica, la fuga es silenciosa.
- **Lo que se sacrificó:** `clinica_id` repetido en las tablas hijas (una desnormalización deliberada, ver sección 5.1 del
  [documento del modelo](diseno-modelo-logico.md)), una restricción única extra `(clinica_id, id)` en las tablas referenciadas,
  y que **el filtro de lectura sigue dependiendo del código**.

### 1.3 Cómo se sostiene I5: tres capas

| Capa | Qué impone | Qué atrapa |
|---|---|---|
| **El motor** | Claves foráneas compuestas | Un error del código que intente atar un dato de una clínica a otra: el motor rechaza la escritura |
| **La sesión** | La clínica sale de la fila del usuario en la base (`sesion.clinica_id`), **nunca** de un parámetro, cuerpo ni cabecera. `Sesion` es inmutable | Un cliente que mande `clinica_id` en la consulta, el cuerpo o `X-Clinica-Id`: se ignora o se rechaza (los esquemas de entrada son `extra="forbid"`) |
| **Cada consulta** | Todo `SELECT` filtra por `clinica_id = sesion.clinica_id`, y todo `JOIN` une también por `clinica_id` | Una lectura que mezcle clínicas |

Detalles que importan:

- **Un id ajeno responde igual que uno inexistente** (404, mismo mensaje). Si respondiera 403, confirmaría que el dato existe en
  otra clínica.
- Los identificadores son `uuid`, así que no se pueden enumerar.
- El **administrador de plataforma** no tiene clínica (`clinica_id` es `NULL`, lo impone un `CHECK` en `usuario`). Las rutas de datos
  clínicos usan `sesion_de_clinica`, que le responde 403: da de alta clínicas pero no ve sus datos.

### 1.4 Cómo se demuestra

- [servicios/pruebas_comunes/aislamiento.py](../servicios/pruebas_comunes/aislamiento.py) (T26): arma dos clínicas iguales, una
  con un "canario" en cada texto. Desde cada rol de la clínica contraria, y como administrador de plataforma, ataca **cada ruta** con
  ids ajenos, ids mezclados, `clinica_id` inyectado y la cabecera `X-Clinica-Id`. Exige respuestas idénticas a las de ids
  inventados, que el canario no aparezca y que una huella (`md5`) de cada tabla de la víctima no cambie.
- Una ruta nueva que no se agregue a la tabla hace fallar `test_todas_las_rutas_estan_en_el_barrido`.
- Unitaria (T33): ninguna ruta de ningún servicio declara `clinica_id` como parámetro ni como campo de entrada.

## 2. Identidad delegada (Keycloak)

El sistema **no implementa** inicio de sesión, emisión ni firma de tokens: lo hace Keycloak, que corre como un contenedor más del
Compose. El trabajo propio es configurar el proveedor y **validar contra él** lo que llega.

### 2.1 El realm

[keycloak/realm-export.json](../keycloak/realm-export.json) está versionado y se importa solo al arrancar
(`start-dev --import-realm`): nada se configura a mano en la consola.

| Elemento | Valor | Por qué |
|---|---|---|
| Realm | `medicitas` | Exclusivo de este sistema |
| Roles | `ADM_PLATAFORMA`, `ADM_CLINICA`, `RECEPCION`, `PROFESIONAL` | Los cuatro actores del enunciado |
| Client `medicitas-web` | Público, flujo *authorization code* con PKCE (`S256`), sin *direct grants* | El login real del frontend |
| Client `medicitas-api` | Público, *direct access grants* habilitado | **Solo** para pruebas y la colección de peticiones: pedir un token con usuario y contraseña desde la línea de comandos |
| `accessTokenLifespan` | 900 s (15 min) | Ver 2.4 |
| Usuarios de prueba | 18, con el mismo `id` que el `keycloak_sub` de la semilla | Que la semilla y el realm coincidan sin pasos manuales |

### 2.2 Qué se valida en cada solicitud

[servicios/comun/medicitas_comun/sesion.py](../servicios/comun/medicitas_comun/sesion.py), un solo punto de entrada para los
tres servicios:

1. **Token:** la firma (`RS256`) contra las llaves públicas del realm (JWKS), el emisor (`iss`), que no esté vencido y que sea un
   token de **acceso** (`typ: Bearer`; un `id_token` lleva la misma firma, pero dice quién inició sesión, no qué puede hacer).
   Cualquier fallo es **401**. Los algoritmos aceptados son solo `RS256`, así que un token con `alg: none` se rechaza.
2. **Usuario:** se busca `usuario.keycloak_sub = token.sub`. Si no existe, 401.
3. **Activo:** se revisa `usuario.activo` en **cada** solicitud. Un usuario dado de baja recibe **403** de inmediato, aunque su token
   siga vigente.
4. **Rol:** si el rol no alcanza para la ruta, **403**.

Si no se pueden consultar las llaves (Keycloak caído y sin llaves en memoria), la respuesta es **503**, no 401: el token puede ser
válido, y no es culpa del cliente que no se haya podido comprobar. Con cualquier valor de `AUTH_MODO` que no sea `keycloak` o
`desarrollo`, todo se rechaza (fallar cerrado).

### 2.3 Cómo se asocia cada identidad con su clínica

> Esta es la pregunta que el enunciado deja abierta y de la que depende I5.

**Cada identidad se enlaza con su clínica en nuestra base, no en el token.** La tabla `usuario` guarda `keycloak_sub` (único), la
`clinica_id` y el `rol_id`. El token solo dice **quién** es la persona (`sub`); la clínica y el rol salen de esa fila.

Alternativas consideradas:

| Alternativa | Ventaja | Por qué no |
|---|---|---|
| **Claim de clínica en el token** (mapper de atributos en Keycloak) | Sin consulta a la base por solicitud | Mover a un usuario de clínica o cambiar su rol exigiría tocar Keycloak y esperar a que el token expire. Y un error de configuración del proveedor rompería I5 sin que el motor lo note |
| **Una clínica por realm o por grupo en Keycloak** | El proveedor aísla a los tenants | Alta de clínica = configurar el proveedor; el administrador de plataforma depende de una API de administración para cada clínica |
| **Leer los roles del claim `realm_access.roles` del token** | Es lo que sugiere RF17 | Ver abajo |

**Decisión sobre el rol:** el rol que se usa para autorizar sale de la tabla `usuario`, no del claim del token. Los roles del
realm existen y se asignan al crear una cuenta (para que la consola de Keycloak sea coherente), pero **no son la fuente de
verdad**. Esto es una **desviación consciente** de la redacción de RF17 («según el rol que viaja en el token»), con este
razonamiento:

- **Cambio inmediato.** Cambiar de rol o dar de baja a alguien surte efecto en la siguiente solicitud, no cuando venza el token
  (hasta 15 minutos). Es la decisión abierta 2 del documento del modelo, resuelta en este sentido.
- **Una sola fuente de verdad** para el invariante I5: clínica y rol viven juntos, protegidos por las mismas claves foráneas.
- **Lo que cuesta:** una consulta por solicitud al identificar al usuario, y que la asignación de roles exista en dos lugares
  (Keycloak y la tabla `usuario`), con la tabla como autoridad. El alta de usuarios (RF1, RF2) hace las dos cosas dentro de una
  operación: primero la fila (que se puede deshacer con `ROLLBACK`), después la cuenta en Keycloak, y si esta falla se deshace
  todo.

### 2.4 Otras decisiones

- **No se valida `aud`.** El realm es exclusivo de MediCitas (lo versiona este repositorio), así que cualquier token que firme viene
  de uno de sus propios clients. Si el realm se compartiera con otra aplicación, ahí se agregaría la validación de `aud` o `azp`.
- **Token de 15 minutos.** Equilibra pedir tokens nuevos con frecuencia contra el tiempo en que un token robado sirve. La baja
  lógica no depende de él (ver 2.2, punto 3).
- **Dos direcciones de Keycloak:** `KEYCLOAK_ISSUER` es la pública (la que viene escrita en el token) y `KEYCLOAK_JWKS_URL` la
  interna de la red de Compose (de donde se bajan las llaves).
- **`sslRequired: none`** es solo para desarrollo local. El cifrado en tránsito corresponde a la Etapa 2.

### 2.5 Cómo se demuestra

[servicios/pruebas_comunes/permisos.py](../servicios/pruebas_comunes/permisos.py) (T29) firma tokens con una llave propia y prueba
401 (sin cabecera, otro esquema, texto basura, otra firma, vencido, otro emisor, `id_token`, sin `sub`, `sub` desconocido,
`alg: none`), 403 (rol equivocado, dado de baja) y 503 (llaves inalcanzables), más la matriz de permisos completa ruta por ruta
y rol por rol. Las unitarias (T33) prueban la misma lógica de decisión sin base de datos, y que la cabecera `X-Usuario-Id` no
suplanta a nadie en modo `keycloak`.

## 3. Roles de base de datos con menor privilegio

Cada servicio se conecta con **su propio rol** ([011_roles.sql](../db/migrations/011_roles.sql)). Ninguno es superusuario ni
dueño de las tablas (siguen siendo de `POSTGRES_USER`, que solo usan las migraciones). Si un servicio se compromete, o una
inyección SQL llega a él, el daño queda limitado a lo que ese servicio necesita.

| Rol | Alineado con | Puede | No puede |
|---|---|---|---|
| `app_agenda` | Horarios, bloqueos y citas (RF5 a RF13, RF20) | Leer el catálogo; insertar y borrar horarios y bloqueos; insertar citas y cambiar **solo** las columnas de estado y cancelación | Ver notas clínicas ni la bitácora; ver teléfono o correo de pacientes; editar los datos de una cita |
| `app_plataforma` | Administración, pacientes y notas (RF1 a RF4, RF14 a RF16) | Escribir clínicas, usuarios, catálogo, profesionales, pacientes y notas; **insertar** en la bitácora; leer citas | Modificar o borrar la bitácora; modificar citas |
| `app_auditoria` | Bitácora y reportes (RF19, RF21) | Leer la bitácora y las columnas mínimas de clínica, paciente (nombre e identificación) y cita (fecha y estado) | Escribir en cualquier tabla; ver notas, teléfono o correo |

Esto se alinea con la matriz de permisos del enunciado en dos niveles: el servicio decide **por rol de usuario** (sección 2) y el
motor limita **por servicio** (esta sección). Un error en el código de `app_auditoria` no puede escribir, y uno en `app_agenda` no
puede leer una nota clínica.

Decisiones y trade-offs:

- **Tres roles, uno por servicio, y no uno por rol de usuario.** Un rol de base por cada actor (administrador, recepción,
  profesional) exigiría una conexión distinta por solicitud o `SET ROLE` constante, y mezclaría la identidad de la persona con la
  del servicio. El rol de usuario ya se aplica en la capa de rutas.
- **Una tabla o columna nueva no queda accesible por sí sola:** la migración que la crea debe darle permisos a cada rol, o el
  servicio falla con `permission denied`. Es incómodo y es lo que se quiere.
- **Excepción documentada.** `SELECT ... FOR NO KEY UPDATE` (el bloqueo de fila de la reserva) exige `UPDATE` sobre al menos una
  columna. Se otorga `UPDATE (id)` sobre `profesional`, `paciente` y `clinica`, columna que ninguna ruta cambia.
- **Contraseñas fuera de los archivos versionados:** la migración crea los roles sin poder iniciar sesión y `aplicar.sh` los habilita
  en cada arranque con la contraseña del `.env`.
- **Consultas parametrizadas:** los valores del usuario viajan siempre como parámetros (`%s` de psycopg), nunca dentro del texto
  SQL. Los comodines de las búsquedas (`%`, `_`, `\`) se escapan para que se busquen literalmente. Donde una consulta se arma con
  texto (`LIMIT`, la lista de columnas, el bloque `WHERE`), lo que se interpola son constantes del propio código, nunca datos del
  cliente.
- **Las pruebas corren como el rol del servicio** (`ROL_PRUEBAS` en el Compose, con `SET LOCAL ROLE`). Así los permisos de esta
  migración se ejercitan en cada prueba de integración: un permiso faltante hace fallar la suite.

## 4. Bitácora de auditoría

### 4.1 Qué se registra (RF18) y quién la consulta (RF19)

- **Qué:** toda **lectura y escritura** de notas clínicas (`NOTA_CLINICA`) y de datos de contacto de pacientes
  (`CONTACTO_PACIENTE`). Cada fila anota **quién** (`usuario_id`), **qué** (`accion` y `recurso`), **sobre cuál paciente**
  (`paciente_id`) y **cuándo** (`ocurrido_en`, que pone el motor con `now()`, no el cliente).
- **En la misma transacción.** El `INSERT` de la bitácora ocurre dentro de la transacción de la operación: o quedan las dos cosas,
  o ninguna. No hay forma de leer una nota sin dejar rastro, ni de dejar un rastro de algo que no ocurrió.
- **Qué no se registra, a propósito.** Los listados de pacientes y el historial (RF16) no traen contacto ni notas, y RF18 solo pide
  esos dos recursos. Una operación rechazada (404, 409) tampoco deja registro: no hubo acceso.
- **Consulta (RF19):** solo el administrador de la clínica, con filtros por usuario, por paciente (texto en nombre o
  identificación) y por rango de fechas interpretado en la zona horaria de la clínica. La consulta filtra por la clínica de la
  sesión, y cada `JOIN` también.

### 4.2 Por qué es append-only a nivel de motor (I6)

I6: la bitácora no admite modificación ni borrado por parte de la aplicación. Una convención del código («nadie la edita») no
alcanza, así que hay **dos barreras independientes**:

| Barrera | Dónde | Qué impide | Qué no impide |
|---|---|---|---|
| **1. Privilegios** | [011_roles.sql](../db/migrations/011_roles.sql) | `app_plataforma` solo tiene `INSERT`; `app_auditoria` solo `SELECT`; `app_agenda` no ve la tabla | Al dueño de la tabla o a un superusuario |
| **2. Trigger** | [010_bitacora_solo_agregar.sql](../db/migrations/010_bitacora_solo_agregar.sql) | Rechaza `UPDATE`, `DELETE` y `TRUNCATE` **sea quien sea**, dueño y superusuario incluidos, también `TRUNCATE ... CASCADE` desde otra tabla | Quien sea dueño puede desactivar el trigger con `ALTER TABLE ... DISABLE TRIGGER` o borrar la tabla |

Las dos barreras se cubren mutuamente: los privilegios detienen a la aplicación aunque alguien desactivara el trigger, y el trigger
detiene incluso a quien tenga los privilegios. Lo que ninguna evita, DDL por un dueño, queda cerrado porque **los servicios no se
conectan como dueño ni como superusuario**. Ambas barreras responden con el mismo código (`42501`), de modo que quien llama no sabe
cuál lo frenó.

### 4.3 Cómo se demuestra

- [db/pruebas/restricciones.sql](../db/pruebas/restricciones.sql): `UPDATE`, `DELETE`, `TRUNCATE` y `TRUNCATE usuario CASCADE` sobre
  la bitácora fallan con `42501`.
- `servicios/agenda/tests/test_invariantes_i3_i6.py` (T30): lo mismo a través de la API, y que el rol de la aplicación no tiene el
  privilegio.
- `servicios/auditoria/tests/test_bitacora.py` y las unitarias (T33): los filtros, el escape de comodines, que la consulta nunca
  escribe, y que cada ruta de plataforma registra la acción correcta sobre el paciente correcto.

## 5. Límites conocidos y decisiones pendientes

Lo que **no** se hizo, dicho con claridad:

1. **RLS no está implementado.** Se comparó en la sección 1 y se descartó como estrategia única. Como capa adicional habría
   protegido las lecturas aunque un `WHERE` se olvidara; hoy esa protección depende del código y de las pruebas de aislamiento.
2. **El rol sale de la base, no del token** (sección 2.3). Es una desviación consciente de la redacción de RF17, con sus razones. Si
   la evaluación exigiera leer el rol del claim, el cambio está acotado a `sesion.py`: las rutas no saben cómo se autenticó nadie.
3. **La bitácora no detecta manipulación por parte de un dueño de la base.** Impide que la **aplicación** la altere (I6), pero quien
   administre la base podría desactivar el trigger. Detectarlo (por ejemplo, encadenando huellas entre registros) es un módulo
   adicional que no se implementó.
4. **Sin cifrado en tránsito ni endurecimiento del despliegue** (`sslRequired: none`, contraseñas de prueba): corresponden a la
   Etapa 2.
5. **El client `medicitas-api` permite contraseña directa.** Es cómodo para las pruebas y la colección de peticiones y no debe
   existir en producción.
6. **Si Keycloak cae**, los tokens ya emitidos siguen funcionando mientras la API conserve las llaves en memoria; no se pueden
   pedir tokens nuevos, y si además la API se reinicia, responde 503 hasta que Keycloak vuelve.
