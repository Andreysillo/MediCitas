import type { Clinica, Usuario } from "./dominio";
import { ApiError, db, nuevoId, red, sesionPlataforma } from "./nucleo";

// Alta de clínicas (RF1). Es lo único que hace el administrador de plataforma: no accede a
// ningún dato clínico, así que aquí solo salen datos de la clínica misma y cuántos usuarios tiene.

/** Zonas horarias que ofrece el formulario. La clínica guarda la suya para interpretar su horario semanal. */
export const ZONAS_HORARIAS = [
  "America/Costa_Rica",
  "America/Panama",
  "America/Guatemala",
  "America/Mexico_City",
  "America/Bogota",
  "America/Lima",
  "America/Santiago",
  "America/Argentina/Buenos_Aires",
  "Europe/Madrid",
] as const;

export type ClinicaResumen = Clinica & { usuarios: number };

export async function listarClinicas(): Promise<ClinicaResumen[]> {
  sesionPlataforma();
  return red(
    db.clinicas
      .map((c) => ({ ...c, usuarios: db.usuarios.filter((u) => u.clinica_id === c.id && u.activo).length }))
      .sort((a, b) => a.nombre.localeCompare(b.nombre, "es")),
  );
}

const IDENTIFICADOR = /^[a-z0-9]+(-[a-z0-9]+)*$/;

/** Crea la clínica y, en el mismo paso, su primer usuario administrador. */
export async function crearClinica(datos: {
  nombre: string;
  identificador: string;
  zona_horaria: string;
  admin_nombre: string;
}): Promise<{ clinica: ClinicaResumen; admin: Usuario }> {
  sesionPlataforma();
  const nombre = datos.nombre.trim().replace(/\s+/g, " ");
  const identificador = datos.identificador.trim().toLowerCase();
  const adminNombre = datos.admin_nombre.trim().replace(/\s+/g, " ");

  if (nombre.length < 3 || nombre.length > 80) throw new ApiError(422, "El nombre de la clínica debe tener entre 3 y 80 caracteres");
  if (identificador.length < 3 || identificador.length > 40 || !IDENTIFICADOR.test(identificador)) {
    throw new ApiError(422, "El identificador usa 3 a 40 letras minúsculas, números y guiones (por ejemplo: clinica-central)");
  }
  if (!(ZONAS_HORARIAS as readonly string[]).includes(datos.zona_horaria)) throw new ApiError(422, "Elige una zona horaria de la lista");
  if (adminNombre.length < 3 || adminNombre.length > 80) throw new ApiError(422, "Escribe el nombre del primer administrador");
  if (db.clinicas.some((c) => c.identificador === identificador)) throw new ApiError(409, "Ya existe una clínica con ese identificador");

  // Todo se valida antes de insertar: o se crean la clínica y su administrador, o ninguno de los dos.
  const clinica: Clinica = { id: nuevoId(), nombre, identificador, zona_horaria: datos.zona_horaria };
  const admin: Usuario = { id: nuevoId(), clinica_id: clinica.id, rol: "ADM_CLINICA", nombre: adminNombre, activo: true };
  db.clinicas.push(clinica);
  db.usuarios.push(admin);
  return red({ clinica: { ...clinica, usuarios: 1 }, admin });
}
