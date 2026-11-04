-- 005: bitácora de lecturas y escrituras sensibles (RF18).
--
-- Esta migración solo crea la tabla. Que sea append-only (I6) lo imponen los privilegios del rol de la
-- aplicación (sin UPDATE, DELETE ni TRUNCATE) y un trigger de respaldo: eso lo agrega la migración de
-- roles de base de datos (T19 y T23).

CREATE TABLE registro_auditoria (
    -- Identidad en vez de uuid: da un orden de inserción que no depende del reloj.
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    clinica_id   uuid        NOT NULL,
    usuario_id   uuid        NOT NULL,
    paciente_id  uuid        NOT NULL,
    accion       text        NOT NULL CHECK (accion IN ('LECTURA', 'ESCRITURA')),
    recurso      text        NOT NULL CHECK (recurso IN ('NOTA_CLINICA', 'CONTACTO_PACIENTE')),
    ocurrido_en  timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (clinica_id, usuario_id)  REFERENCES usuario (clinica_id, id),
    FOREIGN KEY (clinica_id, paciente_id) REFERENCES paciente (clinica_id, id)
);
