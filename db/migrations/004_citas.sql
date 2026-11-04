-- 004: operación clínica. Tablas paciente, cita y nota_clinica, con I1 e I2 sostenidas por el motor.

CREATE TABLE paciente (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id        uuid NOT NULL REFERENCES clinica (id),
    identificacion    text NOT NULL,
    nombre            text NOT NULL,
    fecha_nacimiento  date NOT NULL,
    telefono          text,
    correo            text,
    -- La misma persona puede ser paciente de dos clínicas, pero no dos veces en la misma.
    UNIQUE (clinica_id, identificacion),
    UNIQUE (clinica_id, id)
);

CREATE TABLE cita (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id          uuid        NOT NULL,
    paciente_id         uuid        NOT NULL,
    profesional_id      uuid        NOT NULL,
    servicio_id         uuid        NOT NULL,
    inicio              timestamptz NOT NULL,
    -- Instantánea de inicio + duración del servicio al reservar (I4): si el servicio cambia de duración
    -- después, las citas ya hechas no se mueven. La reserva (RF9) calcula `fin` dentro de su transacción.
    fin                 timestamptz NOT NULL,
    estado              text        NOT NULL DEFAULT 'RESERVADA'
                        CHECK (estado IN ('RESERVADA', 'ATENDIDA', 'AUSENTE', 'CANCELADA', 'REPROGRAMADA')),
    creada_por          uuid        NOT NULL,
    creada_en           timestamptz NOT NULL DEFAULT now(),
    cancelada_por       uuid,
    cancelada_en        timestamptz,
    motivo_cancelacion  text,
    -- Reprogramar no edita la cita: marca la antigua REPROGRAMADA y crea una nueva que apunta a ella.
    -- UNIQUE: una cita reprogramada tiene como máximo una sucesora.
    cita_origen_id      uuid        UNIQUE,

    CHECK (fin > inicio),
    CHECK (cita_origen_id IS DISTINCT FROM id),
    -- Quién, cuándo y por qué se cancela (RF11): los tres datos juntos si y solo si está CANCELADA.
    CONSTRAINT cita_cancelacion_completa CHECK (
        (estado = 'CANCELADA'
            AND cancelada_por IS NOT NULL AND cancelada_en IS NOT NULL AND btrim(motivo_cancelacion) <> '')
        OR
        (estado <> 'CANCELADA'
            AND cancelada_por IS NULL AND cancelada_en IS NULL AND motivo_cancelacion IS NULL)
    ),

    UNIQUE (clinica_id, id),
    FOREIGN KEY (clinica_id, paciente_id) REFERENCES paciente (clinica_id, id),
    -- Tres columnas: solo se agenda un servicio que ese profesional tiene asociado.
    FOREIGN KEY (clinica_id, profesional_id, servicio_id)
        REFERENCES profesional_servicio (clinica_id, profesional_id, servicio_id),
    FOREIGN KEY (clinica_id, creada_por)    REFERENCES usuario (clinica_id, id),
    -- cancelada_por y cita_origen_id admiten NULL: con MATCH SIMPLE, una columna NULL desactiva la clave.
    FOREIGN KEY (clinica_id, cancelada_por) REFERENCES usuario (clinica_id, id),
    FOREIGN KEY (clinica_id, cita_origen_id) REFERENCES cita (clinica_id, id),

    -- I1: un profesional nunca tiene dos citas vigentes solapadas.
    --   - tstzrange con '[)': una cita que termina a las 10:00 no choca con la que empieza a las 10:00.
    --   - WHERE: solo ocupan agenda RESERVADA, ATENDIDA y AUSENTE. Cancelar o reprogramar saca la cita
    --     del conjunto y libera el espacio en la misma transacción (I7).
    --   - La clínica no entra en la condición: profesional_id es un uuid y ya pertenece a una sola clínica.
    -- Si dos transacciones intentan el mismo espacio, la segunda espera a la primera y, si esa confirma,
    -- falla con SQLSTATE 23P01 (exclusion_violation), que la aplicación traduce a 409.
    CONSTRAINT cita_sin_solape_profesional EXCLUDE USING gist (
        profesional_id WITH =,
        tstzrange(inicio, fin, '[)') WITH &&
    ) WHERE (estado IN ('RESERVADA', 'ATENDIDA', 'AUSENTE')),

    -- I2: lo mismo para el paciente, que no puede estar en dos consultas a la vez.
    CONSTRAINT cita_sin_solape_paciente EXCLUDE USING gist (
        paciente_id WITH =,
        tstzrange(inicio, fin, '[)') WITH &&
    ) WHERE (estado IN ('RESERVADA', 'ATENDIDA', 'AUSENTE'))
);

-- Nota clínica (RF15): a lo más una por cita. Que la cita esté ATENDIDA y que la escriba su profesional
-- lo verifica la lógica de la aplicación, porque un CHECK no puede mirar otra tabla.
CREATE TABLE nota_clinica (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    clinica_id      uuid        NOT NULL,
    cita_id         uuid        NOT NULL UNIQUE,
    contenido       text        NOT NULL,
    creada_en       timestamptz NOT NULL DEFAULT now(),
    actualizada_en  timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (clinica_id, cita_id) REFERENCES cita (clinica_id, id)
);
