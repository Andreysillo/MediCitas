// Utilidades de fecha en hora local. Una "fecha" es un texto "YYYY-MM-DD" sin hora.
// Ojo: toISOString() devuelve la fecha en UTC; en Costa Rica (UTC-6) después de las
// 6 p. m. ya daría el día siguiente, por eso aquí se arma a mano con la hora local.

const dos = (n: number) => String(n).padStart(2, "0");

export const fechaLocal = (d: Date) => `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;

export const hoy = () => fechaLocal(new Date());

/** Medianoche local de una fecha "YYYY-MM-DD". */
export const inicioDelDia = (fecha: string) => {
  const [y, m, d] = fecha.split("-").map(Number);
  return new Date(y, m - 1, d);
};

export const sumarDias = (fecha: string, dias: number) => {
  const d = inicioDelDia(fecha);
  d.setDate(d.getDate() + dias);
  return fechaLocal(d);
};

/** Día de la semana ISO: 1 = lunes … 7 = domingo (el mismo criterio que horario_atencion). */
export const diaSemanaIso = (fecha: string) => ((inicioDelDia(fecha).getDay() + 6) % 7) + 1;

/** Minutos desde la medianoche para una hora "08:30". */
export const minutosHora = (hora: string) => {
  const [h, m] = hora.split(":").map(Number);
  return h * 60 + m;
};

const FMT_HORA = new Intl.DateTimeFormat("es-CR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const FMT_FECHA_LARGA = new Intl.DateTimeFormat("es-CR", { weekday: "long", day: "numeric", month: "long" });

export const hora = (instante: string) => FMT_HORA.format(new Date(instante));

export const fechaLarga = (fecha: string) => FMT_FECHA_LARGA.format(inicioDelDia(fecha));

const FMT_FECHA_CORTA = new Intl.DateTimeFormat("es-CR", { weekday: "short", day: "numeric", month: "short" });

/** "jue, 22 oct" */
export const fechaCorta = (fecha: string) => FMT_FECHA_CORTA.format(inicioDelDia(fecha));
