// Tipos del dominio. Los campos usan los mismos nombres que las columnas del
// modelo lógico (docs/diseno-modelo-logico.md) para que al conectar la API real
// no haya que traducir nada.

export type Uuid = string;
/** Instante absoluto en ISO 8601 (timestamptz en la base). */
export type Instante = string;

// Mismos códigos que la tabla `rol` y que los roles del realm de Keycloak.
export type Rol = "ADM_PLATAFORMA" | "ADM_CLINICA" | "RECEPCION" | "PROFESIONAL";

export type EstadoCita = "RESERVADA" | "ATENDIDA" | "AUSENTE" | "CANCELADA" | "REPROGRAMADA";

export type Clinica = {
  id: Uuid;
  nombre: string;
  identificador: string;
  zona_horaria: string;
};

export type Especialidad = { id: Uuid; clinica_id: Uuid; nombre: string };

export type Usuario = {
  id: Uuid;
  clinica_id: Uuid | null; // null solo para ADM_PLATAFORMA (RF2)
  rol: Rol;
  nombre: string;
  activo: boolean;
};

export type Profesional = {
  id: Uuid;
  clinica_id: Uuid;
  usuario_id: Uuid;
  especialidad_id: Uuid;
  numero_colegiado: string;
  activo: boolean;
};

export type Servicio = {
  id: Uuid;
  clinica_id: Uuid;
  nombre: string;
  duracion_minutos: number; // determina el tamaño del espacio que ocupa la cita (I4)
  especialidad_id: Uuid;
  activo: boolean;
};

export type ProfesionalServicio = { clinica_id: Uuid; profesional_id: Uuid; servicio_id: Uuid };

export type HorarioAtencion = {
  id: Uuid;
  clinica_id: Uuid;
  profesional_id: Uuid;
  dia_semana: number; // 1 = lunes … 7 = domingo (ISO)
  hora_inicio: string; // "08:00", hora local de la clínica
  hora_fin: string;
};

export type BloqueoAgenda = {
  id: Uuid;
  clinica_id: Uuid;
  profesional_id: Uuid;
  inicio: Instante;
  fin: Instante;
  motivo: string;
};

export type Paciente = {
  id: Uuid;
  clinica_id: Uuid;
  identificacion: string;
  nombre: string;
  fecha_nacimiento: string; // fecha sin hora, "1990-05-17"
  telefono: string;
  correo: string;
};

/**
 * Nota clínica: el dato más sensible del sistema (RF15). No guarda al autor porque `cita_id`
 * ya determina al profesional; guardarlo sería una dependencia transitiva (3FN).
 */
export type NotaClinica = {
  id: Uuid;
  clinica_id: Uuid;
  cita_id: Uuid; // única: a lo sumo una nota por cita
  contenido: string;
  creada_en: Instante;
  actualizada_en: Instante;
};

/** Bitácora append-only (RF18, I6): quién leyó o escribió qué dato sensible de qué paciente. */
export type RegistroAuditoria = {
  id: number;
  clinica_id: Uuid;
  usuario_id: Uuid;
  paciente_id: Uuid;
  accion: "LECTURA" | "ESCRITURA";
  recurso: "NOTA_CLINICA" | "CONTACTO_PACIENTE";
  ocurrido_en: Instante;
};

export type Cita = {
  id: Uuid;
  clinica_id: Uuid;
  paciente_id: Uuid;
  profesional_id: Uuid;
  servicio_id: Uuid;
  inicio: Instante;
  fin: Instante; // instantánea de la duración al reservar (desnormalización 5.2)
  estado: EstadoCita;
  creada_por: Uuid;
  creada_en: Instante;
  cancelada_por: Uuid | null;
  cancelada_en: Instante | null;
  motivo_cancelacion: string | null;
  cita_origen_id: Uuid | null; // cita que esta reprograma
};

// ---------- Reglas del dominio que la interfaz también necesita ----------

// Matriz de permisos del enunciado (sección 3). Ocultar un botón es comodidad; la API vuelve a comprobarlo.
export const ROLES_QUE_AGENDAN: readonly Rol[] = ["ADM_CLINICA", "RECEPCION"]; // reservar, reprogramar, cancelar
export const ROLES_QUE_EDITAN_PACIENTES: readonly Rol[] = ["ADM_CLINICA", "RECEPCION"]; // el profesional solo lee
export const ROLES_QUE_REGISTRAN_DESENLACE: readonly Rol[] = ["ADM_CLINICA", "RECEPCION", "PROFESIONAL"];

export const ESTADO_NOMBRE: Record<EstadoCita, string> = {
  RESERVADA: "Reservada",
  ATENDIDA: "Atendida",
  AUSENTE: "Ausente",
  CANCELADA: "Cancelada",
  REPROGRAMADA: "Reprogramada",
};

/** Estados que ocupan agenda. CANCELADA y REPROGRAMADA liberan el espacio (I7). */
export const ESTADOS_VIGENTES: readonly EstadoCita[] = ["RESERVADA", "ATENDIDA", "AUSENTE"];

export const esVigente = (estado: EstadoCita) => ESTADOS_VIGENTES.includes(estado);

/** Transiciones permitidas (RF13): solo se sale de RESERVADA; los otros cuatro estados son finales. */
export const TRANSICIONES: Record<EstadoCita, readonly EstadoCita[]> = {
  RESERVADA: ["ATENDIDA", "AUSENTE", "CANCELADA", "REPROGRAMADA"],
  ATENDIDA: [],
  AUSENTE: [],
  CANCELADA: [],
  REPROGRAMADA: [],
};

export const puedeTransicionar = (de: EstadoCita, a: EstadoCita) => TRANSICIONES[de].includes(a);

/** Intervalos semiabiertos [inicio, fin): una cita que termina a las 9:00 no choca con otra que empieza a las 9:00. */
export const seSolapan = (aIni: number, aFin: number, bIni: number, bFin: number) =>
  aIni < bFin && bIni < aFin;
