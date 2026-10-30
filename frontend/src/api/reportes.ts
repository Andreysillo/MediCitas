import { fechaLocal, inicioDelDia, sumarDias } from "../fechas";
import { ESTADO_NOMBRE, type EstadoCita } from "./dominio";
import { ApiError, db, red, sesionConRol } from "./nucleo";

// Conteo de citas por estado en un rango de fechas (RF21). En PostgreSQL es una sola consulta
// agregada (GROUP BY estado) sobre el motor transaccional; la analítica real es de la Etapa 2.

const MAX_DIAS = 366;

export type ReporteEstados = {
  desde: string;
  hasta: string;
  total: number;
  porEstado: Record<EstadoCita, number>;
};

const fechaValida = (f: string) => /^\d{4}-\d{2}-\d{2}$/.test(f) && fechaLocal(inicioDelDia(f)) === f;

/** Cuenta las citas cuyo inicio cae entre `desde` y `hasta`, ambos días incluidos. */
export async function citasPorEstado(desde: string, hasta: string): Promise<ReporteEstados> {
  const { clinica } = sesionConRol(["ADM_CLINICA"], "Solo el administrador de clínica consulta los reportes");
  if (!fechaValida(desde) || !fechaValida(hasta)) throw new ApiError(422, "Las fechas del rango no son válidas");
  if (desde > hasta) throw new ApiError(422, "La fecha inicial no puede ser posterior a la final");
  const ini = inicioDelDia(desde).getTime();
  const fin = inicioDelDia(sumarDias(hasta, 1)).getTime(); // hasta incluido: se corta al día siguiente
  if ((fin - ini) / 86_400_000 > MAX_DIAS + 1) throw new ApiError(422, `El rango no puede pasar de ${MAX_DIAS} días`);

  // Todos los estados salen en el resultado, también los que tienen cero citas.
  const porEstado = Object.fromEntries((Object.keys(ESTADO_NOMBRE) as EstadoCita[]).map((e) => [e, 0])) as Record<EstadoCita, number>;
  let total = 0;
  for (const c of db.citas) {
    const t = Date.parse(c.inicio);
    if (c.clinica_id !== clinica.id || t < ini || t >= fin) continue;
    porEstado[c.estado]++;
    total++;
  }
  return red({ desde, hasta, total, porEstado });
}
