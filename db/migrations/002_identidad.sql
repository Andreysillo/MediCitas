-- 002: tenant e identidad. Tablas clinica, rol, especialidad y usuario.
--
-- Convención de multi-tenancy (I5): toda tabla hija lleva clinica_id, y sus claves foráneas son
-- COMPUESTAS (clinica_id, id). Para poder apuntar a (clinica_id, id), cada tabla padre declara
-- UNIQUE (clinica_id, id). Así el motor impide que una fila de la clínica A referencie una fila de la B,
-- aunque la aplicación tenga un error.

CREATE TABLE clinica (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre         text        NOT NULL,
    -- Texto corto y estable para URL y logs: minúsculas, números y guiones.
    identificador  text        NOT NULL UNIQUE
                   CHECK (identificador ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    -- Zona IANA (America/Costa_Rica). El horario semanal es hora local y se interpreta con esta zona.
    -- La validez del nombre la comprueba la aplicación contra pg_timezone_names al dar de alta (RF1).
    zona_horaria   text        NOT NULL,
    creada_en      timestamptz NOT NULL DEFAULT now()
);

-- Catálogo fijo. Los ids son parte del contrato: el CHECK de usuario depende de que 1 sea la plataforma.
CREATE TABLE rol (
    id      smallint PRIMARY KEY,
    codigo  text     NOT NULL UNIQUE
);

INSERT INTO rol (id, codigo) VALUES
    (1, 'ADM_PLATAFORMA'),
    (2, 'ADM_CLINICA'),
    (3, 'RECEPCION'),
    (4, 'PROFESIONAL');

-- Catálogo propio de cada clínica (decisión del grupo): la matriz de permisos no asigna a nadie un
-- catálogo global, así que lo mantiene el administrador de cada clínica.
CREATE TABLE especialidad (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id  uuid NOT NULL REFERENCES clinica (id),
    nombre      text NOT NULL,
    UNIQUE (clinica_id, nombre),
    UNIQUE (clinica_id, id)
);

-- Las credenciales viven en Keycloak: aquí solo se guarda el identificador que ese proveedor emite
-- (el claim `sub` del token), la clínica y el rol.
CREATE TABLE usuario (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    -- NULL solo para el administrador de plataforma, que no pertenece a ninguna clínica.
    clinica_id   uuid        REFERENCES clinica (id),
    rol_id       smallint    NOT NULL REFERENCES rol (id),
    keycloak_sub text        NOT NULL UNIQUE,
    nombre       text        NOT NULL,
    -- Baja lógica (RF2): nada se borra, porque las citas y la bitácora siguen apuntando al usuario.
    activo       boolean     NOT NULL DEFAULT true,
    creado_en    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (clinica_id, id),
    -- "Una clínica por usuario" (RF2): rol 1 (plataforma) sin clínica, cualquier otro con clínica.
    CONSTRAINT usuario_clinica_segun_rol CHECK ((rol_id = 1) = (clinica_id IS NULL))
);
