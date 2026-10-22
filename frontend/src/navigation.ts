import type { Rol } from "./api/dominio";

export const ROL_NOMBRE: Record<Rol, string> = {
  ADM_PLATAFORMA: "Administración de plataforma",
  ADM_CLINICA: "Administración de clínica",
  RECEPCION: "Recepción",
  PROFESIONAL: "Profesional de salud",
};

export type Ruta = Readonly<{
  path: string;
  titulo: string;
  descripcion: string;
  roles: readonly Rol[];
}>;

// Menú derivado de la matriz de permisos del enunciado (sección 3).
// Ocultar una opción es solo comodidad: quien autoriza de verdad es la API.
export const RUTAS: readonly Ruta[] = [
  {
    path: "/clinicas",
    titulo: "Clínicas",
    descripcion: "Alta de clínicas y de su primer administrador (RF1).",
    roles: ["ADM_PLATAFORMA"],
  },
  {
    path: "/agenda",
    titulo: "Agenda del día",
    descripcion: "Citas del día por profesional o de toda la clínica (RF20).",
    roles: ["ADM_CLINICA", "RECEPCION", "PROFESIONAL"],
  },
  {
    path: "/reservar",
    titulo: "Reservar",
    descripcion: "Buscar espacios disponibles y reservar una cita (RF7 a RF9).",
    roles: ["ADM_CLINICA", "RECEPCION"],
  },
  {
    path: "/pacientes",
    titulo: "Pacientes",
    descripcion: "Registro de pacientes e historial de citas (RF14, RF16).",
    roles: ["ADM_CLINICA", "RECEPCION", "PROFESIONAL"],
  },
  {
    path: "/horarios",
    titulo: "Horarios y bloqueos",
    descripcion: "Horario semanal y bloqueos de agenda (RF5, RF6).",
    roles: ["ADM_CLINICA", "PROFESIONAL"],
  },
  {
    path: "/catalogo",
    titulo: "Catálogo",
    descripcion: "Especialidades, servicios y profesionales (RF3, RF4).",
    roles: ["ADM_CLINICA"],
  },
  {
    path: "/usuarios",
    titulo: "Usuarios",
    descripcion: "Alta, baja lógica y rol de los usuarios (RF2).",
    roles: ["ADM_CLINICA"],
  },
  {
    path: "/reportes",
    titulo: "Reportes",
    descripcion: "Citas por estado en un rango de fechas (RF21).",
    roles: ["ADM_CLINICA"],
  },
  {
    path: "/bitacora",
    titulo: "Bitácora",
    descripcion: "Accesos a notas clínicas y datos de contacto (RF19).",
    roles: ["ADM_CLINICA"],
  },
];

export const rutasDe = (rol: Rol) => RUTAS.filter((r) => r.roles.includes(rol));
