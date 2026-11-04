-- 003: lo que define cuándo y qué puede atender cada profesional.
-- Tablas profesional, servicio, profesional_servicio, horario_atencion y bloqueo_agenda.

CREATE TABLE profesional (
    id                uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id        uuid    NOT NULL,
    -- Un usuario es a lo sumo un profesional: solo quien tiene rol PROFESIONAL tiene fila aquí.
    usuario_id        uuid    NOT NULL UNIQUE,
    especialidad_id   uuid    NOT NULL,
    numero_colegiado  text    NOT NULL,
    activo            boolean NOT NULL DEFAULT true,
    UNIQUE (clinica_id, id),
    FOREIGN KEY (clinica_id, usuario_id)      REFERENCES usuario (clinica_id, id),
    FOREIGN KEY (clinica_id, especialidad_id) REFERENCES especialidad (clinica_id, id)
);

CREATE TABLE servicio (
    id                uuid    PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id        uuid    NOT NULL REFERENCES clinica (id),
    nombre            text    NOT NULL,
    -- La duración del servicio decide cuánto espacio ocupa la cita (I4).
    duracion_minutos  integer NOT NULL CHECK (duracion_minutos > 0),
    especialidad_id   uuid    NOT NULL,
    activo            boolean NOT NULL DEFAULT true,
    UNIQUE (clinica_id, nombre),
    UNIQUE (clinica_id, id),
    FOREIGN KEY (clinica_id, especialidad_id) REFERENCES especialidad (clinica_id, id)
);

-- Qué servicios atiende cada profesional. La clave primaria lleva clinica_id porque cita la referencia
-- con tres columnas: así el motor garantiza que solo se agenda un servicio habilitado para ese profesional.
CREATE TABLE profesional_servicio (
    clinica_id      uuid    NOT NULL,
    profesional_id  uuid    NOT NULL,
    servicio_id     uuid    NOT NULL,
    -- Deshabilitar no borra: las citas ya hechas siguen apuntando a la pareja.
    activo          boolean NOT NULL DEFAULT true,
    PRIMARY KEY (clinica_id, profesional_id, servicio_id),
    FOREIGN KEY (clinica_id, profesional_id) REFERENCES profesional (clinica_id, id),
    FOREIGN KEY (clinica_id, servicio_id)    REFERENCES servicio (clinica_id, id)
);

-- Horario semanal (RF5). Hora local de la clínica; varios bloques por día son varias filas
-- (por ejemplo 08:00-12:00 y 13:00-17:00).
CREATE TABLE horario_atencion (
    id              uuid     PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id      uuid     NOT NULL,
    profesional_id  uuid     NOT NULL,
    dia_semana      smallint NOT NULL CHECK (dia_semana BETWEEN 1 AND 7),  -- ISO: 1 lunes ... 7 domingo
    hora_inicio     time     NOT NULL,
    hora_fin        time     NOT NULL,
    CHECK (hora_fin > hora_inicio),
    FOREIGN KEY (clinica_id, profesional_id) REFERENCES profesional (clinica_id, id),
    -- Un CHECK solo ve su propia fila, así que "sin solape de bloques" necesita una exclusión.
    -- '[)' deja pasar bloques contiguos (08:00-12:00 y 12:00-13:00) pero no 08:00-12:00 y 11:00-13:00.
    CONSTRAINT horario_sin_solape EXCLUDE USING gist (
        profesional_id WITH =,
        dia_semana     WITH =,
        timerange(hora_inicio, hora_fin, '[)') WITH &&
    )
);

-- Bloqueos por vacaciones o permisos (RF6). Son instantes absolutos. Un bloqueo nuevo NO cancela citas:
-- las que caen dentro se listan como conflicto, y quien agenda decide qué hacer con ellas.
CREATE TABLE bloqueo_agenda (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id      uuid        NOT NULL,
    profesional_id  uuid        NOT NULL,
    inicio          timestamptz NOT NULL,
    fin             timestamptz NOT NULL,
    motivo          text        NOT NULL,
    CHECK (fin > inicio),
    FOREIGN KEY (clinica_id, profesional_id) REFERENCES profesional (clinica_id, id)
);
