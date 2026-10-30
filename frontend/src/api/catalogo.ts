import type { Especialidad, Profesional } from "./dominio";
import { ApiError, db, nombreUsuario, nuevoId, red, sesionConRol } from "./nucleo";

// Catálogo de la clínica (RF3, RF4): especialidades, servicios y profesionales con los servicios
// que atienden. Solo lo mantiene el administrador de clínica (matriz de permisos).

const mismoNombre = (a: string, b: string) => a.localeCompare(b, "es", { sensitivity: "base" }) === 0;

const adminDeClinica = () => sesionConRol(["ADM_CLINICA"], "Solo el administrador de clínica mantiene el catálogo").clinica;

function validarNombre(nombre: string, que: string) {
  const limpio = nombre.trim().replace(/\s+/g, " ");
  if (limpio.length < 3 || limpio.length > 60) throw new ApiError(422, `El nombre de ${que} debe tener entre 3 y 60 caracteres`);
  return limpio;
}

// ---------- Especialidades ----------

export async function listarEspecialidades(): Promise<Especialidad[]> {
  const clinica = adminDeClinica();
  return red(db.especialidades.filter((e) => e.clinica_id === clinica.id).sort((a, b) => a.nombre.localeCompare(b.nombre, "es")));
}

/** La especialidad es propia de cada clínica (decisión de diseño): su nombre es único solo dentro de ella. */
export async function crearEspecialidad(nombre: string): Promise<Especialidad> {
  const clinica = adminDeClinica();
  const limpio = validarNombre(nombre, "la especialidad");
  if (db.especialidades.some((e) => e.clinica_id === clinica.id && mismoNombre(e.nombre, limpio))) {
    throw new ApiError(409, "Ya existe una especialidad con ese nombre");
  }
  const especialidad: Especialidad = { id: nuevoId(), clinica_id: clinica.id, nombre: limpio };
  db.especialidades.push(especialidad);
  return red(especialidad);
}

// ---------- Servicios (RF3) ----------

export type ServicioAdmin = {
  id: string;
  nombre: string;
  duracion_minutos: number;
  especialidad_id: string;
  especialidad: string;
  activo: boolean;
};

const MIN_DURACION = 5;
const MAX_DURACION = 480;

function validarDuracion(minutos: number) {
  if (!Number.isInteger(minutos) || minutos < MIN_DURACION || minutos > MAX_DURACION) {
    throw new ApiError(422, `La duración debe ser un número entero de minutos entre ${MIN_DURACION} y ${MAX_DURACION}`);
  }
}

const servicioAdmin = (s: (typeof db.servicios)[number]): ServicioAdmin => ({
  id: s.id,
  nombre: s.nombre,
  duracion_minutos: s.duracion_minutos,
  especialidad_id: s.especialidad_id,
  especialidad: db.especialidades.find((e) => e.id === s.especialidad_id)?.nombre ?? "—",
  activo: s.activo,
});

/** Todos los servicios de la clínica, también los desactivados (a diferencia de `listarServicios`, que sirve para reservar). */
export async function listarServiciosAdmin(): Promise<ServicioAdmin[]> {
  const clinica = adminDeClinica();
  return red(
    db.servicios
      .filter((s) => s.clinica_id === clinica.id)
      .map(servicioAdmin)
      .sort((a, b) => a.especialidad.localeCompare(b.especialidad, "es") || a.nombre.localeCompare(b.nombre, "es")),
  );
}

export async function crearServicio(datos: { nombre: string; duracion_minutos: number; especialidad_id: string }): Promise<ServicioAdmin> {
  const clinica = adminDeClinica();
  const nombre = validarNombre(datos.nombre, "el servicio");
  validarDuracion(datos.duracion_minutos);
  // La clave compuesta (clinica_id, especialidad_id) impide usar la especialidad de otra clínica.
  if (!db.especialidades.some((e) => e.id === datos.especialidad_id && e.clinica_id === clinica.id)) {
    throw new ApiError(422, "La especialidad no existe en esta clínica");
  }
  if (db.servicios.some((s) => s.clinica_id === clinica.id && mismoNombre(s.nombre, nombre))) {
    throw new ApiError(409, "Ya existe un servicio con ese nombre");
  }
  const servicio = {
    id: nuevoId(),
    clinica_id: clinica.id,
    nombre,
    duracion_minutos: datos.duracion_minutos,
    especialidad_id: datos.especialidad_id,
    activo: true,
  };
  db.servicios.push(servicio);
  return red(servicioAdmin(servicio));
}

/**
 * Edita un servicio. La especialidad no se cambia: los profesionales ya asociados la comparten.
 * Cambiar la duración solo afecta a las citas nuevas: cada cita guarda su propio `fin` (I4).
 */
export async function actualizarServicio(
  id: string,
  datos: { nombre: string; duracion_minutos: number; activo: boolean },
): Promise<ServicioAdmin> {
  const clinica = adminDeClinica();
  const servicio = db.servicios.find((s) => s.id === id && s.clinica_id === clinica.id);
  if (!servicio) throw new ApiError(404, "Servicio no encontrado");
  const nombre = validarNombre(datos.nombre, "el servicio");
  validarDuracion(datos.duracion_minutos);
  if (db.servicios.some((s) => s.clinica_id === clinica.id && s.id !== id && mismoNombre(s.nombre, nombre))) {
    throw new ApiError(409, "Ya existe un servicio con ese nombre");
  }
  Object.assign(servicio, { nombre, duracion_minutos: datos.duracion_minutos, activo: datos.activo });
  return red(servicioAdmin(servicio));
}

// ---------- Profesionales (RF4) ----------

export type ProfesionalAdmin = {
  id: string;
  nombre: string;
  especialidad_id: string;
  especialidad: string;
  numero_colegiado: string;
  activo: boolean;
  servicios_ids: string[];
};

const profesionalAdmin = (p: Profesional): ProfesionalAdmin => ({
  id: p.id,
  nombre: nombreUsuario(p.usuario_id),
  especialidad_id: p.especialidad_id,
  especialidad: db.especialidades.find((e) => e.id === p.especialidad_id)?.nombre ?? "—",
  numero_colegiado: p.numero_colegiado,
  activo: p.activo,
  servicios_ids: db.profesionalServicio.filter((ps) => ps.profesional_id === p.id && ps.activo).map((ps) => ps.servicio_id),
});

export async function listarProfesionalesAdmin(): Promise<ProfesionalAdmin[]> {
  const clinica = adminDeClinica();
  return red(
    db.profesionales
      .filter((p) => p.clinica_id === clinica.id)
      .map(profesionalAdmin)
      .sort((a, b) => a.nombre.localeCompare(b.nombre, "es")),
  );
}

/** Usuarios con rol de profesional que todavía no tienen su registro de profesional. */
export async function usuariosProfesionalesLibres(): Promise<{ id: string; nombre: string }[]> {
  const clinica = adminDeClinica();
  const yaRegistrados = new Set(db.profesionales.map((p) => p.usuario_id));
  return red(
    db.usuarios
      .filter((u) => u.clinica_id === clinica.id && u.rol === "PROFESIONAL" && u.activo && !yaRegistrados.has(u.id))
      .map(({ id, nombre }) => ({ id, nombre })),
  );
}

export type DatosProfesional = { especialidad_id: string; numero_colegiado: string; servicios_ids: string[] };

function validarDatosProfesional(clinicaId: string, d: DatosProfesional) {
  const colegiado = d.numero_colegiado.trim();
  if (colegiado.length < 3 || colegiado.length > 20) throw new ApiError(422, "El número de colegiado debe tener entre 3 y 20 caracteres");
  if (!db.especialidades.some((e) => e.id === d.especialidad_id && e.clinica_id === clinicaId)) {
    throw new ApiError(422, "La especialidad no existe en esta clínica");
  }
  // Un profesional solo atiende servicios de su especialidad (RF3, RF4).
  const permitidos = new Set(
    db.servicios.filter((s) => s.clinica_id === clinicaId && s.especialidad_id === d.especialidad_id).map((s) => s.id),
  );
  if (d.servicios_ids.some((id) => !permitidos.has(id))) {
    throw new ApiError(422, "Un servicio no existe o no corresponde a la especialidad del profesional");
  }
  return colegiado;
}

/**
 * Deja habilitados exactamente los servicios indicados. Lo que se quita se desactiva, no se borra:
 * las citas existentes referencian la pareja (profesional, servicio) y la clave foránea lo impediría.
 */
function aplicarServicios(p: Profesional, ids: string[]) {
  for (const ps of db.profesionalServicio) {
    if (ps.profesional_id === p.id) ps.activo = ids.includes(ps.servicio_id);
  }
  for (const id of ids) {
    if (!db.profesionalServicio.some((ps) => ps.profesional_id === p.id && ps.servicio_id === id)) {
      db.profesionalServicio.push({ clinica_id: p.clinica_id, profesional_id: p.id, servicio_id: id, activo: true });
    }
  }
}

export async function crearProfesional(datos: DatosProfesional & { usuario_id: string }): Promise<ProfesionalAdmin> {
  const clinica = adminDeClinica();
  const usuario = db.usuarios.find((u) => u.id === datos.usuario_id && u.clinica_id === clinica.id);
  if (!usuario || usuario.rol !== "PROFESIONAL" || !usuario.activo) {
    throw new ApiError(422, "El usuario no existe en esta clínica o no tiene rol de profesional");
  }
  if (db.profesionales.some((p) => p.usuario_id === usuario.id)) throw new ApiError(409, "Ese usuario ya está registrado como profesional");
  const numero_colegiado = validarDatosProfesional(clinica.id, datos);

  const profesional: Profesional = {
    id: nuevoId(),
    clinica_id: clinica.id,
    usuario_id: usuario.id,
    especialidad_id: datos.especialidad_id,
    numero_colegiado,
    activo: true,
  };
  db.profesionales.push(profesional);
  aplicarServicios(profesional, datos.servicios_ids);
  return red(profesionalAdmin(profesional));
}

export async function actualizarProfesional(id: string, datos: DatosProfesional): Promise<ProfesionalAdmin> {
  const clinica = adminDeClinica();
  const profesional = db.profesionales.find((p) => p.id === id && p.clinica_id === clinica.id);
  if (!profesional) throw new ApiError(404, "Profesional no encontrado");
  const numero_colegiado = validarDatosProfesional(clinica.id, datos);
  Object.assign(profesional, { especialidad_id: datos.especialidad_id, numero_colegiado });
  aplicarServicios(profesional, datos.servicios_ids);
  return red(profesionalAdmin(profesional));
}
