import { inicioDelDia, sumarDias } from "../fechas";
import type { Instante, RegistroAuditoria, Rol } from "./dominio";
import { ApiError, db, nombreUsuario, red, sesionConRol, sinTildes } from "./nucleo";

// Consulta de la bitácora de auditoría (RF19). Solo la lee el administrador de clínica, y aquí
// no existe ninguna función que la modifique o la borre (I6).

const LIMITE = 100;

export type FiltrosAuditoria = {
  usuarioId?: string;
  /** Texto: se busca en el nombre y la identificación del paciente. */
  paciente?: string;
  /** Fechas "YYYY-MM-DD", ambas incluidas. */
  desde?: string;
  hasta?: string;
};

export type RegistroVista = {
  id: number;
  ocurrido_en: Instante;
  usuario: string;
  rol: Rol | null;
  accion: RegistroAuditoria["accion"];
  recurso: RegistroAuditoria["recurso"];
  paciente: string;
  identificacion: string;
};

export async function listarAuditoria(f: FiltrosAuditoria = {}): Promise<{ total: number; registros: RegistroVista[] }> {
  const { clinica } = sesionConRol(["ADM_CLINICA"], "Solo el administrador de clínica consulta la bitácora");
  if (f.desde && f.hasta && f.desde > f.hasta) throw new ApiError(422, "La fecha inicial no puede ser posterior a la final");
  const ini = f.desde ? inicioDelDia(f.desde).getTime() : -Infinity;
  const fin = f.hasta ? inicioDelDia(sumarDias(f.hasta, 1)).getTime() : Infinity;
  const q = sinTildes((f.paciente ?? "").trim());

  const pacientes = new Map(db.pacientes.filter((p) => p.clinica_id === clinica.id).map((p) => [p.id, p]));
  const encontrados = db.auditoria
    .filter((r) => {
      if (r.clinica_id !== clinica.id) return false; // I5: la bitácora de otra clínica no existe para esta
      if (f.usuarioId && r.usuario_id !== f.usuarioId) return false;
      const t = Date.parse(r.ocurrido_en);
      if (t < ini || t >= fin) return false;
      if (!q) return true;
      const p = pacientes.get(r.paciente_id);
      return !!p && (sinTildes(p.nombre).includes(q) || p.identificacion.includes(q));
    })
    .sort((a, b) => Date.parse(b.ocurrido_en) - Date.parse(a.ocurrido_en) || b.id - a.id);

  return red({
    total: encontrados.length,
    registros: encontrados.slice(0, LIMITE).map((r) => ({
      id: r.id,
      ocurrido_en: r.ocurrido_en,
      usuario: nombreUsuario(r.usuario_id),
      rol: db.usuarios.find((u) => u.id === r.usuario_id)?.rol ?? null,
      accion: r.accion,
      recurso: r.recurso,
      paciente: pacientes.get(r.paciente_id)?.nombre ?? "—",
      identificacion: pacientes.get(r.paciente_id)?.identificacion ?? "—",
    })),
  });
}
