import type { Rol, Usuario } from "./dominio";
import { ApiError, db, nuevoId, red, sesionConRol } from "./nucleo";

// Usuarios de la clínica (RF2): alta, baja lógica y asignación de rol. Las credenciales no viven
// aquí: las administra Keycloak. Este módulo solo guarda quién pertenece a la clínica y con qué rol.

const adminDeClinica = () => sesionConRol(["ADM_CLINICA"], "Solo el administrador de clínica gestiona los usuarios");

/** El administrador de plataforma no se asigna desde una clínica: no pertenece a ninguna (RF2). */
export const ROLES_ASIGNABLES: readonly Rol[] = ["ADM_CLINICA", "RECEPCION", "PROFESIONAL"];

export type UsuarioVista = { id: string; nombre: string; rol: Rol; activo: boolean; es_profesional: boolean; yo: boolean };

function vista(u: Usuario, yoId: string): UsuarioVista {
  return {
    id: u.id,
    nombre: u.nombre,
    rol: u.rol,
    activo: u.activo,
    es_profesional: db.profesionales.some((p) => p.usuario_id === u.id),
    yo: u.id === yoId,
  };
}

function buscarUsuario(id: string) {
  const { usuario: yo, clinica } = adminDeClinica();
  // Un usuario de otra clínica responde como si no existiera (I5).
  const usuario = db.usuarios.find((u) => u.id === id && u.clinica_id === clinica.id);
  if (!usuario) throw new ApiError(404, "Usuario no encontrado");
  return { usuario, yo, clinica };
}

export async function listarUsuarios(): Promise<UsuarioVista[]> {
  const { usuario: yo, clinica } = adminDeClinica();
  return red(
    db.usuarios
      .filter((u) => u.clinica_id === clinica.id)
      .map((u) => vista(u, yo.id))
      .sort((a, b) => Number(b.activo) - Number(a.activo) || a.nombre.localeCompare(b.nombre, "es")),
  );
}

export async function crearUsuario(datos: { nombre: string; rol: Rol }): Promise<UsuarioVista> {
  const { usuario: yo, clinica } = adminDeClinica();
  const nombre = datos.nombre.trim().replace(/\s+/g, " ");
  if (nombre.length < 3 || nombre.length > 80) throw new ApiError(422, "El nombre debe tener entre 3 y 80 caracteres");
  if (!ROLES_ASIGNABLES.includes(datos.rol)) throw new ApiError(422, "Ese rol no se puede asignar dentro de una clínica");
  const usuario: Usuario = { id: nuevoId(), clinica_id: clinica.id, rol: datos.rol, nombre, activo: true };
  db.usuarios.push(usuario);
  return red(vista(usuario, yo.id));
}

export async function cambiarRol(id: string, rol: Rol): Promise<UsuarioVista> {
  const { usuario, yo } = buscarUsuario(id);
  if (!ROLES_ASIGNABLES.includes(rol)) throw new ApiError(422, "Ese rol no se puede asignar dentro de una clínica");
  if (usuario.id === yo.id) throw new ApiError(409, "No puedes cambiar tu propio rol");
  // Su registro de profesional (agenda, servicios, citas) depende de que siga siendo profesional.
  if (rol !== "PROFESIONAL" && db.profesionales.some((p) => p.usuario_id === usuario.id)) {
    throw new ApiError(409, "Es un profesional registrado: no puede cambiar de rol");
  }
  usuario.rol = rol;
  return red(vista(usuario, yo.id));
}

/**
 * Baja lógica o reactivación. Nada se borra: las citas y la bitácora siguen apuntando al usuario.
 * Si es profesional, también sale (o vuelve) a la disponibilidad. Sus citas reservadas no se cancelan:
 * se informa cuántas quedan pendientes para que recepción las reprograme.
 */
export async function cambiarActivo(id: string, activo: boolean): Promise<{ usuario: UsuarioVista; citas_pendientes: number }> {
  const { usuario, yo } = buscarUsuario(id);
  // Como nadie puede darse de baja ni cambiarse el rol a sí mismo, quien actúa (un administrador activo)
  // siempre sigue ahí: la clínica nunca se queda sin administrador.
  if (!activo && usuario.id === yo.id) throw new ApiError(409, "No puedes darte de baja a ti mismo");
  usuario.activo = activo;

  let citas_pendientes = 0;
  const profesional = db.profesionales.find((p) => p.usuario_id === usuario.id);
  if (profesional) {
    profesional.activo = activo;
    if (!activo) {
      citas_pendientes = db.citas.filter(
        (c) => c.profesional_id === profesional.id && c.estado === "RESERVADA" && Date.parse(c.fin) > Date.now(),
      ).length;
    }
  }
  return red({ usuario: vista(usuario, yo.id), citas_pendientes });
}
