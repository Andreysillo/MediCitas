import { diaSemanaIso, fechaLocal, hoy, inicioDelDia, sumarDias } from "../fechas";
import { espaciosLibres, instanteEn } from "./disponibilidad";
import {
  ESTADO_NOMBRE,
  ROLES_QUE_AGENDAN,
  ROLES_QUE_EDITAN_PACIENTES,
  ROLES_QUE_REGISTRAN_DESENLACE,
  esVigente,
  puedeTransicionar,
  seSolapan,
  type BloqueoAgenda,
  type Cita,
  type EstadoCita,
  type HorarioAtencion,
  type Instante,
  type NotaClinica,
  type Paciente,
  type Usuario,
} from "./dominio";
import {
  ApiError,
  auditar,
  citaVista,
  db,
  fijarSesion,
  nombreUsuario,
  nuevoId,
  red,
  sesionDeClinica,
  sinTildes,
  type CitaVista,
  type Sesion,
} from "./nucleo";

export { ApiError, sesionVigente, suscribirSesion, type CitaVista, type Sesion } from "./nucleo";
export * from "./auditoria";
export * from "./catalogo";
export * from "./clinicas";
export * from "./horarios";
export * from "./reportes";
export * from "./usuarios";

// Capa de acceso a datos del frontend. Hoy responde desde memoria; cuando exista
// el backend, cada función se cambia por un fetch a la API y las vistas no se tocan.
// Este archivo tiene la agenda, la reserva y los pacientes; el resto vive en módulos
// aparte (horarios, catálogo, usuarios...) que se reexportan al final.

/** Usuarios de prueba agrupados por clínica, para la pantalla de ingreso a la demo. Solo los que pueden iniciar sesión. */
export function usuariosDePrueba() {
  const activos = db.usuarios.filter((u) => u.activo);
  const grupos: { clinicaId: string | null; etiqueta: string; usuarios: Usuario[] }[] = [
    { clinicaId: null, etiqueta: "Plataforma MediCitas", usuarios: activos.filter((u) => u.clinica_id === null) },
  ];
  for (const c of db.clinicas) {
    grupos.push({ clinicaId: c.id, etiqueta: c.nombre, usuarios: activos.filter((u) => u.clinica_id === c.id) });
  }
  return grupos;
}

/**
 * Simula el inicio de sesión. Con Keycloak la clínica y el rol vendrán dentro del token,
 * y la API tomará la clínica de ahí, nunca de un parámetro de la solicitud (I5).
 */
export function iniciarSesion(usuarioId: string): Sesion {
  const usuario = db.usuarios.find((u) => u.id === usuarioId);
  if (!usuario) throw new Error(`Usuario de prueba inexistente: ${usuarioId}`);
  if (!usuario.activo) throw new ApiError(403, "Tu usuario fue dado de baja");
  const sesion = { usuario, clinica: db.clinicas.find((c) => c.id === usuario.clinica_id) ?? null };
  fijarSesion(sesion);
  return sesion;
}

/** Simula el cierre de sesión. Con Keycloak será su logout, que invalida el token. */
export function cerrarSesion() {
  fijarSesion(null);
}

// ---------- Profesionales ----------

export type ProfesionalVista = { id: string; nombre: string; especialidad: string };

const profesionalesDe = (clinicaId: string): ProfesionalVista[] =>
  db.profesionales
    .filter((p) => p.clinica_id === clinicaId && p.activo)
    .map((p) => ({
      id: p.id,
      nombre: nombreUsuario(p.usuario_id),
      especialidad: db.especialidades.find((e) => e.id === p.especialidad_id)?.nombre ?? "—",
    }));

// async: así un error de sesión llega como promesa rechazada al .catch de la vista.
export const listarProfesionales = async () => red(profesionalesDe(sesionDeClinica().clinica.id));

// ---------- Agenda del día (RF20) ----------

export type AgendaDia = {
  fecha: string;
  profesionales: ProfesionalVista[];
  horarios: HorarioAtencion[];
  bloqueos: BloqueoAgenda[];
  citas: CitaVista[];
};

/** Agenda de un día: de toda la clínica o de un profesional. */
export async function agendaDelDia(fecha: string, profesionalId?: string): Promise<AgendaDia> {
  const { usuario, clinica } = sesionDeClinica();
  // Parte de los profesionales de la clínica de la sesión: un id de otra clínica no encuentra nada.
  let profesionales = profesionalesDe(clinica.id);

  if (usuario.rol === "PROFESIONAL") {
    // Un profesional solo ve su propia agenda, aunque pida la de otro.
    const propio = db.profesionales.find((p) => p.usuario_id === usuario.id);
    profesionales = profesionales.filter((p) => p.id === propio?.id);
  } else if (profesionalId) {
    profesionales = profesionales.filter((p) => p.id === profesionalId);
  }

  const ids = new Set(profesionales.map((p) => p.id));
  const ini = inicioDelDia(fecha).getTime();
  const fin = inicioDelDia(sumarDias(fecha, 1)).getTime();
  const delDia = (x: { inicio: string; fin: string }) => seSolapan(ini, fin, Date.parse(x.inicio), Date.parse(x.fin));
  const dia = diaSemanaIso(fecha);

  return red({
    fecha,
    profesionales,
    horarios: db.horarios.filter((h) => ids.has(h.profesional_id) && h.dia_semana === dia),
    bloqueos: db.bloqueos.filter((b) => ids.has(b.profesional_id) && delDia(b)),
    citas: db.citas.filter((c) => ids.has(c.profesional_id) && delDia(c)).map(citaVista),
  });
}

// ---------- Servicios ----------

export type ServicioVista = { id: string; nombre: string; duracion_minutos: number; especialidad: string };

export async function listarServicios(): Promise<ServicioVista[]> {
  const { clinica } = sesionDeClinica();
  return red(
    db.servicios
      .filter((s) => s.clinica_id === clinica.id && s.activo)
      .map((s) => ({
        id: s.id,
        nombre: s.nombre,
        duracion_minutos: s.duracion_minutos,
        especialidad: db.especialidades.find((e) => e.id === s.especialidad_id)?.nombre ?? "—",
      })),
  );
}

// ---------- Disponibilidad (RF7, RF8) ----------

export type DisponibilidadProfesional = {
  profesional: ProfesionalVista;
  dias: { fecha: string; espacios: Instante[] }[];
};

const MIN = 60_000;

/**
 * Intervalos ocupados de un profesional: sus citas vigentes y sus bloqueos.
 * `ignorar` es la cita que se está reprogramando: su espacio se libera dentro de la misma
 * transacción (RF10), así que no debe contar como ocupado para elegir el nuevo.
 */
const ocupadosDe = (profesionalId: string, ignorar?: string) => [
  ...db.citas
    .filter((c) => c.profesional_id === profesionalId && c.id !== ignorar && esVigente(c.estado))
    .map((c) => [Date.parse(c.inicio), Date.parse(c.fin)] as const),
  ...db.bloqueos
    .filter((b) => b.profesional_id === profesionalId)
    .map((b) => [Date.parse(b.inicio), Date.parse(b.fin)] as const),
];

const horariosDe = (profesionalId: string, fecha: string) =>
  db.horarios.filter((h) => h.profesional_id === profesionalId && h.dia_semana === diaSemanaIso(fecha));

/** Disponibilidad de un servicio en un rango de días: qué profesionales tienen espacio y cuáles son. */
export async function disponibilidad(
  servicioId: string,
  desde: string,
  dias: number,
  ignorarCitaId?: string,
): Promise<DisponibilidadProfesional[]> {
  const { clinica } = sesionDeClinica();
  const servicio = db.servicios.find((s) => s.id === servicioId && s.clinica_id === clinica.id);
  if (!servicio) throw new ApiError(404, "Servicio no encontrado");
  if (dias < 1 || dias > 31) throw new ApiError(422, "El rango debe ser de 1 a 31 días");

  // Solo los profesionales habilitados para ese servicio (profesional_servicio).
  const habilitados = new Set(db.profesionalServicio.filter((ps) => ps.activo && ps.servicio_id === servicio.id).map((ps) => ps.profesional_id));
  const fechas = Array.from({ length: dias }, (_, i) => sumarDias(desde, i));
  const ahora = Date.now();

  return red(
    profesionalesDe(clinica.id)
      .filter((p) => habilitados.has(p.id))
      .map((profesional) => {
        const ocupados = ocupadosDe(profesional.id, ignorarCitaId);
        return {
          profesional,
          dias: fechas.map((fecha) => ({
            fecha,
            espacios: espaciosLibres(fecha, servicio.duracion_minutos, horariosDe(profesional.id, fecha), ocupados, ahora).map(
              (ms) => new Date(ms).toISOString(),
            ),
          })),
        };
      }),
  );
}

// ---------- Pacientes ----------

export type PacienteResumen = Pick<Paciente, "id" | "nombre" | "identificacion">;

const coincide = (p: Paciente, q: string) => sinTildes(p.nombre).includes(q) || p.identificacion.includes(q);

/**
 * Busca por nombre o identificación. No devuelve teléfono ni correo a propósito:
 * leer datos de contacto se audita (RF18) y para elegir un paciente no hacen falta.
 */
export async function buscarPacientes(texto: string): Promise<PacienteResumen[]> {
  const { clinica } = sesionDeClinica();
  const q = sinTildes(texto.trim());
  if (q.length < 2) return [];
  return red(
    db.pacientes
      .filter((p) => p.clinica_id === clinica.id && coincide(p, q))
      .slice(0, 8)
      .map(({ id, nombre, identificacion }) => ({ id, nombre, identificacion })),
  );
}

// ---------- Reserva (RF9) ----------

/** Lo que envía el cliente. No lleva `fin` ni `clinica_id`: el fin lo fija el servicio (I4) y la clínica la sesión (I5). */
export type SolicitudReserva = { paciente_id: string; profesional_id: string; servicio_id: string; inicio: Instante };

function insertarCita(sol: SolicitudReserva, fin: number, creada_por: string, clinica_id: string, origen: string | null = null): Cita {
  const cita: Cita = {
    id: nuevoId(),
    clinica_id,
    ...sol,
    inicio: new Date(Date.parse(sol.inicio)).toISOString(),
    fin: new Date(fin).toISOString(),
    estado: "RESERVADA",
    creada_por,
    creada_en: new Date().toISOString(),
    cancelada_por: null,
    cancelada_en: null,
    motivo_cancelacion: null,
    cita_origen_id: origen,
  };
  db.citas.push(cita);
  return cita;
}

/**
 * Reglas que debe cumplir un espacio para recibir una cita. Las comparten reservar y
 * reprogramar, para que ambas operaciones nunca discrepen. `ignorar` es la cita que se
 * está moviendo: en la base su estado pasa a REPROGRAMADA antes del insert, así que
 * ya no cuenta para I1 ni I2.
 */
function validarEspacio(clinicaId: string, sol: SolicitudReserva, ignorar?: string) {
  // Un id de otra clínica se trata igual que uno inexistente: no se revela que existe (I5).
  const paciente = db.pacientes.find((p) => p.id === sol.paciente_id && p.clinica_id === clinicaId);
  const profesional = db.profesionales.find((p) => p.id === sol.profesional_id && p.clinica_id === clinicaId);
  const servicio = db.servicios.find((s) => s.id === sol.servicio_id && s.clinica_id === clinicaId);
  if (!paciente || !profesional || !servicio) {
    throw new ApiError(422, "El paciente, el profesional o el servicio no existen en esta clínica");
  }
  if (!servicio.activo) throw new ApiError(422, "El servicio está desactivado");
  if (!profesional.activo) throw new ApiError(422, "El profesional no está activo");
  if (!db.profesionalServicio.some((ps) => ps.activo && ps.profesional_id === profesional.id && ps.servicio_id === servicio.id)) {
    throw new ApiError(422, "El profesional no atiende ese servicio");
  }

  const ini = Date.parse(sol.inicio);
  if (Number.isNaN(ini)) throw new ApiError(422, "La hora de inicio no es válida");
  if (ini <= Date.now()) throw new ApiError(422, "No se puede reservar en el pasado");
  const fin = ini + servicio.duracion_minutos * MIN; // I4: la duración la decide el servicio

  // I3: dentro del horario de atención y fuera de los bloqueos.
  const fecha = fechaLocal(new Date(ini));
  const enHorario = horariosDe(profesional.id, fecha).some(
    (h) => ini >= instanteEn(fecha, h.hora_inicio) && fin <= instanteEn(fecha, h.hora_fin),
  );
  if (!enHorario) throw new ApiError(422, "Ese horario está fuera de la atención del profesional");
  const bloqueado = db.bloqueos.some(
    (b) => b.profesional_id === profesional.id && seSolapan(ini, fin, Date.parse(b.inicio), Date.parse(b.fin)),
  );
  if (bloqueado) throw new ApiError(422, "El profesional tiene un bloqueo de agenda en ese horario");

  // I1 e I2: ningún solape con citas vigentes del profesional ni del paciente.
  const choques = db.citas.filter(
    (c) => c.id !== ignorar && esVigente(c.estado) && seSolapan(ini, fin, Date.parse(c.inicio), Date.parse(c.fin)),
  );
  if (choques.some((c) => c.profesional_id === profesional.id)) throw new ApiError(409, "Ese espacio ya fue tomado");
  if (choques.some((c) => c.paciente_id === paciente.id)) throw new ApiError(409, "El paciente ya tiene otra cita a esa hora");

  return fin;
}

/**
 * Reserva una cita. Mismos desenlaces que la API real:
 * concedida (201), espacio ya tomado (409) o solicitud inválida (422).
 *
 * ponytail: aquí JavaScript ejecuta todo de corrido y no hay carrera real. En el backend,
 * quien decide entre dos reservas simultáneas es la restricción de exclusión de PostgreSQL.
 */
export async function reservarCita(sol: SolicitudReserva): Promise<CitaVista> {
  const { usuario, clinica } = sesionDeClinica();
  if (!ROLES_QUE_AGENDAN.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede reservar citas");
  const fin = validarEspacio(clinica.id, sol);
  return red(citaVista(insertarCita(sol, fin, usuario.id, clinica.id)));
}

/**
 * Solo para la demostración: otra recepcionista reserva ese mismo espacio para otro
 * paciente justo antes. Permite ver en la interfaz el desenlace 409 de la pregunta rectora.
 */
export function simularReservaAjena(sol: SolicitudReserva) {
  const { clinica } = sesionDeClinica();
  const servicio = db.servicios.find((s) => s.id === sol.servicio_id && s.clinica_id === clinica.id);
  const recepcion = db.usuarios.find((u) => u.clinica_id === clinica.id && u.rol === "RECEPCION");
  if (!servicio || !recepcion) return;
  const ini = Date.parse(sol.inicio);
  const fin = ini + servicio.duracion_minutos * MIN;
  const libre = (p: Paciente) =>
    !db.citas.some((c) => c.paciente_id === p.id && esVigente(c.estado) && seSolapan(ini, fin, Date.parse(c.inicio), Date.parse(c.fin)));
  const otro = db.pacientes.find((p) => p.clinica_id === clinica.id && p.id !== sol.paciente_id && libre(p));
  if (otro) insertarCita({ ...sol, paciente_id: otro.id }, fin, recepcion.id, clinica.id);
}

// ---------- Ciclo de vida de la cita (RF10 a RF13) ----------

/** Busca una cita de la clínica de la sesión. Un profesional solo alcanza las suyas. */
function buscarCita(citaId: string) {
  const { usuario, clinica } = sesionDeClinica();
  const cita = db.citas.find((c) => c.id === citaId && c.clinica_id === clinica.id);
  const propio = db.profesionales.find((p) => p.usuario_id === usuario.id);
  // Misma respuesta para "no existe" y "es de otra clínica o de otro profesional" (I5).
  if (!cita || (usuario.rol === "PROFESIONAL" && cita.profesional_id !== propio?.id)) {
    throw new ApiError(404, "Cita no encontrada");
  }
  return { cita, usuario, clinica };
}

/**
 * RF13: único punto por donde cambia el estado de una cita. Si la transición no está en
 * la tabla, se rechaza con 409. En la base lo reforzará un trigger.
 */
function exigirTransicion(cita: Cita, a: EstadoCita) {
  if (!puedeTransicionar(cita.estado, a)) {
    throw new ApiError(409, `Una cita ${ESTADO_NOMBRE[cita.estado].toLowerCase()} no puede pasar a ${ESTADO_NOMBRE[a].toLowerCase()}`);
  }
}

function transicionar(cita: Cita, a: EstadoCita) {
  exigirTransicion(cita, a);
  cita.estado = a;
}

/** RF12: registra si el paciente fue atendido o no se presentó. Solo después de la hora de inicio. */
export async function registrarDesenlace(citaId: string, desenlace: "ATENDIDA" | "AUSENTE"): Promise<CitaVista> {
  const { cita, usuario } = buscarCita(citaId);
  if (!ROLES_QUE_REGISTRAN_DESENLACE.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede registrar el desenlace");
  if (desenlace !== "ATENDIDA" && desenlace !== "AUSENTE") throw new ApiError(422, "El desenlace debe ser atendida o ausente");
  exigirTransicion(cita, desenlace);
  if (Date.parse(cita.inicio) > Date.now()) {
    throw new ApiError(422, "El desenlace solo se registra una vez pasada la hora de inicio");
  }
  transicionar(cita, desenlace);
  return red(citaVista(cita));
}

/** RF11: cancela dejando el motivo y quién lo hizo. Libera el espacio de inmediato (I7). */
export async function cancelarCita(citaId: string, motivo: string): Promise<CitaVista> {
  const { cita, usuario } = buscarCita(citaId);
  if (!ROLES_QUE_AGENDAN.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede cancelar citas");
  if (motivo.trim().length < 3) throw new ApiError(422, "Indica el motivo de la cancelación");
  transicionar(cita, "CANCELADA");
  cita.cancelada_por = usuario.id;
  cita.cancelada_en = new Date().toISOString();
  cita.motivo_cancelacion = motivo.trim();
  return red(citaVista(cita));
}

/**
 * RF10: mueve una cita a otro espacio. No edita la cita: la antigua pasa a REPROGRAMADA y
 * se crea una nueva que apunta a ella (cita_origen_id). El servicio no cambia, así que la
 * duración tampoco (I4).
 *
 * Todo se valida antes de tocar nada, así que o se hacen los dos cambios o ninguno: si el
 * nuevo espacio está tomado, la cita original sigue reservada. En la base esto es una sola
 * transacción: UPDATE de la antigua e INSERT de la nueva se confirman juntos.
 */
export async function reprogramarCita(citaId: string, destino: { profesional_id: string; inicio: Instante }): Promise<CitaVista> {
  const { cita, usuario, clinica } = buscarCita(citaId);
  if (!ROLES_QUE_AGENDAN.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede reprogramar citas");
  exigirTransicion(cita, "REPROGRAMADA");

  const sol: SolicitudReserva = { paciente_id: cita.paciente_id, servicio_id: cita.servicio_id, ...destino };
  if (destino.profesional_id === cita.profesional_id && Date.parse(destino.inicio) === Date.parse(cita.inicio)) {
    throw new ApiError(422, "Elige un espacio distinto al actual");
  }
  const fin = validarEspacio(clinica.id, sol, cita.id);

  transicionar(cita, "REPROGRAMADA");
  return red(citaVista(insertarCita(sol, fin, usuario.id, clinica.id, cita.id)));
}

// ---------- Pacientes (RF14) e historial (RF16) ----------

const LIMITE_LISTA = 50;

export type PacienteLista = Pick<Paciente, "id" | "nombre" | "identificacion" | "fecha_nacimiento">;

/**
 * Listado para elegir un paciente. No incluye teléfono ni correo: esos datos solo salen
 * al abrir la ficha, que es lo que se audita. Devuelve el total para avisar si hay más.
 */
export async function listarPacientes(texto = ""): Promise<{ total: number; pacientes: PacienteLista[] }> {
  const { clinica } = sesionDeClinica();
  const q = sinTildes(texto.trim());
  const todos = db.pacientes
    .filter((p) => p.clinica_id === clinica.id && (q === "" || coincide(p, q)))
    .sort((a, b) => a.nombre.localeCompare(b.nombre, "es"));
  return red({
    total: todos.length,
    pacientes: todos.slice(0, LIMITE_LISTA).map(({ id, nombre, identificacion, fecha_nacimiento }) => ({ id, nombre, identificacion, fecha_nacimiento })),
  });
}

function buscarPaciente(id: string) {
  const { usuario, clinica } = sesionDeClinica();
  // Igual que con las citas: un paciente de otra clínica responde como si no existiera (I5).
  const paciente = db.pacientes.find((p) => p.id === id && p.clinica_id === clinica.id);
  if (!paciente) throw new ApiError(404, "Paciente no encontrado");
  return { paciente, usuario, clinica };
}

/** Ficha completa, con datos de contacto. Cada lectura queda en la bitácora (RF18). */
export async function obtenerPaciente(id: string): Promise<Paciente> {
  const { paciente, usuario, clinica } = buscarPaciente(id);
  auditar(usuario.id, clinica.id, paciente.id, "LECTURA");
  return red(paciente);
}

export type DatosPaciente = Omit<Paciente, "id" | "clinica_id">;

/** Valida y normaliza lo que llega del formulario. Aunque el formulario ya valida, la API no confía en él. */
function validarDatosPaciente(d: DatosPaciente): DatosPaciente {
  const limpio: DatosPaciente = {
    identificacion: d.identificacion.trim(),
    nombre: d.nombre.trim().replace(/\s+/g, " "),
    fecha_nacimiento: d.fecha_nacimiento,
    telefono: d.telefono.trim(),
    correo: d.correo.trim().toLowerCase(),
  };
  if (!limpio.identificacion) throw new ApiError(422, "La identificación es obligatoria");
  if (limpio.nombre.length < 3) throw new ApiError(422, "Escribe el nombre completo");
  // El viaje de ida y vuelta detecta fechas imposibles como 2026-02-31, que Date acomodaría al mes siguiente.
  const f = limpio.fecha_nacimiento;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(f) || fechaLocal(inicioDelDia(f)) !== f) throw new ApiError(422, "La fecha de nacimiento no es válida");
  if (f > hoy() || f < "1900-01-01") throw new ApiError(422, "La fecha de nacimiento está fuera de rango");
  if (limpio.telefono && !/^[+\d][\d\s-]{6,}$/.test(limpio.telefono)) throw new ApiError(422, "El teléfono no es válido");
  if (limpio.correo && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(limpio.correo)) throw new ApiError(422, "El correo no es válido");
  return limpio;
}

/** (clinica_id, identificacion) es única: en la base lo garantiza una restricción UNIQUE. */
function exigirIdentificacionLibre(clinicaId: string, identificacion: string, propio?: string) {
  if (db.pacientes.some((p) => p.clinica_id === clinicaId && p.identificacion === identificacion && p.id !== propio)) {
    throw new ApiError(409, "Ya existe un paciente con esa identificación en la clínica");
  }
}

export async function crearPaciente(datos: DatosPaciente): Promise<Paciente> {
  const { usuario, clinica } = sesionDeClinica();
  if (!ROLES_QUE_EDITAN_PACIENTES.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede registrar pacientes");
  const limpio = validarDatosPaciente(datos);
  exigirIdentificacionLibre(clinica.id, limpio.identificacion);
  const paciente: Paciente = { id: nuevoId(), clinica_id: clinica.id, ...limpio };
  db.pacientes.push(paciente);
  auditar(usuario.id, clinica.id, paciente.id, "ESCRITURA");
  return red(paciente);
}

export async function actualizarPaciente(id: string, datos: DatosPaciente): Promise<Paciente> {
  const { paciente, usuario, clinica } = buscarPaciente(id);
  if (!ROLES_QUE_EDITAN_PACIENTES.includes(usuario.rol)) throw new ApiError(403, "Tu rol no puede modificar pacientes");
  const limpio = validarDatosPaciente(datos);
  exigirIdentificacionLibre(clinica.id, limpio.identificacion, paciente.id);
  Object.assign(paciente, limpio);
  auditar(usuario.id, clinica.id, paciente.id, "ESCRITURA");
  return red(paciente);
}

export type CitaHistorial = CitaVista & { profesional: string };

/** Todas las citas del paciente en su clínica, con su estado, de la más reciente a la más antigua (RF16). */
export async function historialPaciente(id: string): Promise<CitaHistorial[]> {
  const { paciente } = buscarPaciente(id);
  const nombreProfesional = (profesionalId: string) => {
    const p = db.profesionales.find((x) => x.id === profesionalId);
    return p ? nombreUsuario(p.usuario_id) : "—";
  };
  return red(
    db.citas
      .filter((c) => c.paciente_id === paciente.id && c.clinica_id === paciente.clinica_id)
      .sort((a, b) => Date.parse(b.inicio) - Date.parse(a.inicio))
      .map((c) => ({ ...citaVista(c), profesional: nombreProfesional(c.profesional_id) })),
  );
}

// ---------- Nota clínica (RF15) ----------

const MAX_NOTA = 5000;

/**
 * Cita sobre la que el profesional puede trabajar su nota. Solo el profesional que atendió
 * la cita llega aquí: `buscarCita` responde 404 si la cita es de otro profesional, y el resto
 * de los roles reciben 403. Ni recepción ni el administrador de clínica acceden a las notas.
 */
function citaConNota(citaId: string) {
  const { cita, usuario, clinica } = buscarCita(citaId);
  if (usuario.rol !== "PROFESIONAL") throw new ApiError(403, "Solo el profesional que atendió la cita accede a su nota clínica");
  return { cita, usuario, clinica };
}

/** Lee la nota de una cita. Cada lectura queda en la bitácora (RF18). */
export async function obtenerNota(citaId: string): Promise<NotaClinica> {
  const { cita, usuario, clinica } = citaConNota(citaId);
  const nota = db.notas.find((n) => n.cita_id === cita.id);
  if (!nota) throw new ApiError(404, "Esta cita todavía no tiene nota");
  auditar(usuario.id, clinica.id, cita.paciente_id, "LECTURA", "NOTA_CLINICA");
  return red(nota);
}

/**
 * Crea la nota de la cita o reemplaza su contenido si ya existía (una nota por cita).
 * Solo sobre citas ATENDIDAS: antes de eso no hay nada que anotar.
 */
export async function guardarNota(citaId: string, contenido: string): Promise<NotaClinica> {
  const { cita, usuario, clinica } = citaConNota(citaId);
  if (cita.estado !== "ATENDIDA") throw new ApiError(409, "Solo se escribe una nota sobre una cita atendida");
  const texto = contenido.trim();
  if (!texto) throw new ApiError(422, "La nota no puede estar vacía");
  if (texto.length > MAX_NOTA) throw new ApiError(422, `La nota no puede pasar de ${MAX_NOTA} caracteres`);

  const ahora = new Date().toISOString();
  let nota = db.notas.find((n) => n.cita_id === cita.id);
  if (nota) {
    nota.contenido = texto;
    nota.actualizada_en = ahora;
  } else {
    nota = { id: nuevoId(), clinica_id: clinica.id, cita_id: cita.id, contenido: texto, creada_en: ahora, actualizada_en: ahora };
    db.notas.push(nota);
  }
  auditar(usuario.id, clinica.id, cita.paciente_id, "ESCRITURA", "NOTA_CLINICA");
  return red(nota);
}
