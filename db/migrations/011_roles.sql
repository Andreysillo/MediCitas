-- 011: roles de base de datos con menor privilegio (T19).
--
-- Un rol por servicio. Ninguno es dueño de las tablas ni superusuario, así que un error o una inyección en un servicio
-- queda limitado a lo que ese servicio necesita. Las tablas siguen siendo de POSTGRES_USER, que solo usan las migraciones.
--
--   app_agenda      horarios, bloqueos y citas. No ve notas clínicas, bitácora ni teléfono/correo de pacientes.
--   app_plataforma  clínicas, usuarios, catálogo, profesionales, pacientes y notas. En la bitácora solo INSERT.
--   app_auditoria   solo lectura, y solo las columnas que necesita.
--
-- Aquí se crean sin contraseña y sin poder iniciar sesión. Lo que las habilita, con la contraseña del .env, es
-- aplicar.sh, porque una contraseña no debe vivir en un archivo versionado.
--
-- Una tabla o columna nueva no queda accesible por sí sola: la migración que la crea debe darle sus permisos a cada rol.

DO $$
DECLARE r text;
BEGIN
    FOREACH r IN ARRAY ARRAY['app_agenda', 'app_plataforma', 'app_auditoria'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('CREATE ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', r);
        END IF;
    END LOOP;
END $$;

-- Todos los servicios identifican al usuario (sesion_actual): usuario y rol.
GRANT SELECT ON usuario, rol TO app_agenda, app_plataforma, app_auditoria;

-- ---------- agenda ----------
GRANT SELECT ON especialidad, servicio, profesional, profesional_servicio TO app_agenda;
GRANT SELECT (id, zona_horaria) ON clinica TO app_agenda;
GRANT SELECT (id, clinica_id, nombre) ON paciente TO app_agenda;
GRANT SELECT, INSERT, DELETE ON horario_atencion, bloqueo_agenda TO app_agenda;
GRANT SELECT, INSERT ON cita TO app_agenda;
-- Una cita no se edita (007): solo cambia de estado y, al cancelarla, quién, cuándo y por qué.
GRANT UPDATE (estado, cancelada_por, cancelada_en, motivo_cancelacion) ON cita TO app_agenda;
-- FOR NO KEY UPDATE (el bloqueo de fila de la reserva) exige UPDATE sobre al menos una columna. Se da sobre `id`, que
-- ninguna ruta cambia: sirve para bloquear la fila sin permitir editar nada útil.
GRANT UPDATE (id) ON profesional, paciente TO app_agenda;

-- ---------- plataforma ----------
GRANT SELECT, INSERT, UPDATE ON usuario, servicio, profesional, profesional_servicio, paciente, nota_clinica TO app_plataforma;
GRANT SELECT, INSERT ON especialidad TO app_plataforma;
GRANT SELECT, INSERT ON clinica TO app_plataforma;
GRANT UPDATE (id) ON clinica TO app_plataforma;   -- solo para el FOR NO KEY UPDATE de usuarios.py; ver el comentario de agenda
GRANT SELECT ON cita TO app_plataforma;           -- historial (RF16), notas (RF15) y citas pendientes al dar de baja
GRANT INSERT ON registro_auditoria TO app_plataforma;

-- ---------- auditoría ----------
GRANT SELECT ON registro_auditoria TO app_auditoria;
GRANT SELECT (id, zona_horaria) ON clinica TO app_auditoria;
GRANT SELECT (id, clinica_id, identificacion, nombre) ON paciente TO app_auditoria;
GRANT SELECT (clinica_id, inicio, estado) ON cita TO app_auditoria;
