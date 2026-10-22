import {
  esVigente,
  seSolapan,
  type BloqueoAgenda,
  type Cita,
  type Clinica,
  type EstadoCita,
  type Especialidad,
  type HorarioAtencion,
  type Paciente,
  type Profesional,
  type ProfesionalServicio,
  type Rol,
  type Servicio,
  type Usuario,
} from "./dominio";

// Datos de prueba en memoria. Reemplazan a la base mientras no exista el backend:
// 3 clínicas, varios profesionales por clínica y citas de -14 a +14 días respecto de hoy.

export type Datos = {
  clinicas: Clinica[];
  especialidades: Especialidad[];
  usuarios: Usuario[];
  profesionales: Profesional[];
  servicios: Servicio[];
  profesionalServicio: ProfesionalServicio[];
  horarios: HorarioAtencion[];
  bloqueos: BloqueoAgenda[];
  pacientes: Paciente[];
  citas: Cita[];
};

type Jornada = "completa" | "manana" | "tarde";

type DefClinica = {
  nombre: string;
  identificador: string;
  especialidades: { nombre: string; servicios: [string, number][] }[];
  profesionales: { nombre: string; especialidad: string; jornada: Jornada }[];
  admin: string;
  recepcion: string;
};

const CLINICAS: DefClinica[] = [
  {
    nombre: "Clínica San Rafael",
    identificador: "san-rafael",
    especialidades: [
      { nombre: "Medicina general", servicios: [["Consulta general", 20], ["Certificado médico", 15]] },
      { nombre: "Pediatría", servicios: [["Control de niño sano", 30], ["Consulta pediátrica", 20]] },
      { nombre: "Odontología", servicios: [["Limpieza dental", 45], ["Valoración odontológica", 30]] },
    ],
    profesionales: [
      { nombre: "Dra. Laura Méndez", especialidad: "Medicina general", jornada: "completa" },
      { nombre: "Dr. Carlos Jiménez", especialidad: "Medicina general", jornada: "manana" },
      { nombre: "Dra. Sofía Vargas", especialidad: "Pediatría", jornada: "tarde" },
      { nombre: "Dr. Andrés Rojas", especialidad: "Odontología", jornada: "completa" },
    ],
    admin: "Marta Solís",
    recepcion: "Daniela Chaves",
  },
  {
    nombre: "Centro Médico del Valle",
    identificador: "del-valle",
    especialidades: [
      { nombre: "Medicina general", servicios: [["Consulta general", 30]] },
      { nombre: "Dermatología", servicios: [["Consulta dermatológica", 30], ["Crioterapia", 15]] },
      { nombre: "Ginecología", servicios: [["Control ginecológico", 30], ["Ultrasonido", 45]] },
    ],
    profesionales: [
      { nombre: "Dr. Esteban Quesada", especialidad: "Medicina general", jornada: "completa" },
      { nombre: "Dra. Valeria Castro", especialidad: "Dermatología", jornada: "manana" },
      { nombre: "Dra. Paula Arias", especialidad: "Ginecología", jornada: "completa" },
    ],
    admin: "Jorge Herrera",
    recepcion: "Karla Monge",
  },
  {
    nombre: "Clínica Los Robles",
    identificador: "los-robles",
    especialidades: [
      { nombre: "Fisioterapia", servicios: [["Sesión de fisioterapia", 60], ["Evaluación inicial", 45]] },
      { nombre: "Nutrición", servicios: [["Consulta nutricional", 45], ["Control nutricional", 30]] },
      { nombre: "Psicología", servicios: [["Sesión de psicoterapia", 60]] },
    ],
    profesionales: [
      { nombre: "Lic. Diego Navarro", especialidad: "Fisioterapia", jornada: "completa" },
      { nombre: "Lic. Gabriela Soto", especialidad: "Fisioterapia", jornada: "tarde" },
      { nombre: "Lic. Natalia Pérez", especialidad: "Nutrición", jornada: "manana" },
      { nombre: "Dr. Mauricio León", especialidad: "Psicología", jornada: "tarde" },
    ],
    admin: "Silvia Alfaro",
    recepcion: "Fernanda Ruiz",
  },
];

// Bloques semanales por jornada. La "completa" es una jornada partida (ejemplo de RF5).
const JORNADAS: Record<Jornada, { dias: number[]; bloques: [string, string][] }> = {
  completa: { dias: [1, 2, 3, 4, 5], bloques: [["08:00", "12:00"], ["13:00", "17:00"]] },
  manana: { dias: [1, 2, 3, 4, 5, 6], bloques: [["07:00", "12:00"]] },
  tarde: { dias: [1, 2, 3, 4, 5], bloques: [["13:00", "19:00"]] },
};

const NOMBRES = ["Ana", "Luis", "María", "José", "Lucía", "Javier", "Camila", "Mateo", "Isabel", "Pablo", "Elena", "Tomás", "Rebeca", "Adrián", "Valentina", "Hugo", "Mariana", "Felipe", "Carolina", "Sebastián"];
const APELLIDOS = ["Alvarado", "Brenes", "Calderón", "Esquivel", "Fallas", "Granados", "Hidalgo", "Leiva", "Madrigal", "Mora", "Murillo", "Obando", "Picado", "Ramírez", "Salazar", "Ugalde", "Villalobos", "Zúñiga"];
const MOTIVOS_CANCELACION = ["El paciente avisó que no puede asistir", "Cambio de planes del paciente", "Enfermedad del paciente", "Solicitud por teléfono"];

const MIN = 60_000;
const DIA = 24 * 60 * MIN;

// Generador pseudoaleatorio con semilla fija (mulberry32): los mismos datos en cada
// recarga y en cada computadora, así ambos integrantes prueban sobre lo mismo.
function mulberry32(semilla: number) {
  return () => {
    semilla = (semilla + 0x6d2b79f5) | 0;
    let t = Math.imul(semilla ^ (semilla >>> 15), 1 | semilla);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function crearSemilla(hoy = new Date()): Datos {
  const azar = mulberry32(20261022);
  const elegir = <T,>(xs: readonly T[]) => xs[Math.floor(azar() * xs.length)];
  const entre = (min: number, max: number) => min + Math.floor(azar() * (max - min + 1));
  const uuid = () =>
    "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = Math.floor(azar() * 16);
      return (c === "x" ? r : (r & 3) | 8).toString(16);
    });

  // ponytail: las horas se interpretan en la zona del navegador, no en clinica.zona_horaria.
  // Todas las clínicas de prueba están en Costa Rica, así que coincide; la API real sí convertirá.
  const medianoche = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate()).getTime();
  const enDia = (offset: number, hora: string) => {
    const [h, m] = hora.split(":").map(Number);
    const d = new Date(medianoche);
    d.setDate(d.getDate() + offset); // setDate respeta cambios de horario, sumar 24 h no
    d.setHours(h, m, 0, 0);
    return d.getTime();
  };
  const iso = (ms: number) => new Date(ms).toISOString();

  const datos: Datos = {
    clinicas: [], especialidades: [], usuarios: [], profesionales: [], servicios: [],
    profesionalServicio: [], horarios: [], bloqueos: [], pacientes: [], citas: [],
  };

  const usuario = (clinica_id: string | null, rol: Rol, nombre: string) => {
    const u: Usuario = { id: uuid(), clinica_id, rol, nombre, activo: true };
    datos.usuarios.push(u);
    return u;
  };

  usuario(null, "ADM_PLATAFORMA", "Equipo MediCitas");

  for (const def of CLINICAS) {
    const clinica: Clinica = { id: uuid(), nombre: def.nombre, identificador: def.identificador, zona_horaria: "America/Costa_Rica" };
    datos.clinicas.push(clinica);
    const cid = clinica.id;

    usuario(cid, "ADM_CLINICA", def.admin);
    const recepcion = usuario(cid, "RECEPCION", def.recepcion);

    // Especialidades y servicios: catálogo propio de cada clínica.
    const especialidadPorNombre = new Map<string, Especialidad>();
    const serviciosPorEspecialidad = new Map<string, Servicio[]>();
    for (const e of def.especialidades) {
      const esp: Especialidad = { id: uuid(), clinica_id: cid, nombre: e.nombre };
      datos.especialidades.push(esp);
      especialidadPorNombre.set(e.nombre, esp);
      const servicios = e.servicios.map(([nombre, duracion_minutos]): Servicio => (
        { id: uuid(), clinica_id: cid, nombre, duracion_minutos, especialidad_id: esp.id, activo: true }
      ));
      datos.servicios.push(...servicios);
      serviciosPorEspecialidad.set(esp.id, servicios);
    }

    // Pacientes de la clínica. La identificación sigue el formato de cédula costarricense.
    const pacientes: Paciente[] = [];
    for (let i = 0; i < 80; i++) {
      const nombre = `${elegir(NOMBRES)} ${elegir(APELLIDOS)} ${elegir(APELLIDOS)}`;
      const usuarioCorreo = nombre.split(" ").slice(0, 2).join(".").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
      pacientes.push({
        id: uuid(),
        clinica_id: cid,
        identificacion: `${entre(1, 7)}-${String(entre(100, 1999)).padStart(4, "0")}-${String(entre(100, 999)).padStart(4, "0")}`,
        nombre,
        fecha_nacimiento: `${entre(1950, 2022)}-${String(entre(1, 12)).padStart(2, "0")}-${String(entre(1, 28)).padStart(2, "0")}`,
        telefono: `${elegir(["6", "7", "8"])}${entre(100, 999)}-${entre(1000, 9999)}`,
        correo: `${usuarioCorreo}${entre(1, 99)}@correo.cr`,
      });
    }
    datos.pacientes.push(...pacientes);

    // Intervalos vigentes de cada paciente: para no generar citas que violen I2.
    const ocupacionPaciente = new Map<string, [number, number][]>();

    def.profesionales.forEach((p, idx) => {
      const esp = especialidadPorNombre.get(p.especialidad)!;
      const prof: Profesional = {
        id: uuid(),
        clinica_id: cid,
        usuario_id: usuario(cid, "PROFESIONAL", p.nombre).id,
        especialidad_id: esp.id,
        numero_colegiado: `COL-${entre(1000, 9999)}`,
        activo: true,
      };
      datos.profesionales.push(prof);

      // Solo servicios de su especialidad (regla de RF3/RF4).
      const servicios = serviciosPorEspecialidad.get(esp.id)!;
      for (const s of servicios) datos.profesionalServicio.push({ clinica_id: cid, profesional_id: prof.id, servicio_id: s.id });

      const jornada = JORNADAS[p.jornada];
      for (const dia_semana of jornada.dias) {
        for (const [hora_inicio, hora_fin] of jornada.bloques) {
          datos.horarios.push({ id: uuid(), clinica_id: cid, profesional_id: prof.id, dia_semana, hora_inicio, hora_fin });
        }
      }

      // Un bloqueo por clínica en el primer profesional: un permiso mañana a media mañana.
      // Se registra después de que existían citas, así que algunas quedan como conflicto (RF6).
      if (idx === 0) {
        datos.bloqueos.push({ id: uuid(), clinica_id: cid, profesional_id: prof.id, inicio: iso(enDia(1, "10:00")), fin: iso(enDia(1, "12:00")), motivo: "Permiso personal" });
      }

      // Citas: se recorre cada bloque del horario y se van llenando espacios al azar.
      // Como se avanza secuencialmente, las citas de un profesional nunca se solapan (I1).
      for (let offset = -14; offset <= 14; offset++) {
        const fecha = new Date(enDia(offset, "00:00"));
        const diaIso = ((fecha.getDay() + 6) % 7) + 1; // getDay: 0 = domingo → ISO 7
        if (!jornada.dias.includes(diaIso)) continue;
        // La agenda se ve más llena cerca de hoy y más vacía hacia el futuro.
        const ocupacion = offset <= 0 ? 0.7 : Math.max(0.15, 0.7 - offset * 0.05);

        for (const [ini, fin] of jornada.bloques) {
          let t = enDia(offset, ini);
          const limite = enDia(offset, fin);
          while (t < limite) {
            const servicio = elegir(servicios);
            const finCita = t + servicio.duracion_minutos * MIN;
            if (finCita > limite) break;
            if (azar() > ocupacion) {
              t += 15 * MIN;
              continue;
            }
            // Busca un paciente libre en ese intervalo (I2); si no hay, deja el espacio vacío.
            // Se empieza en un paciente al azar para repartir las citas entre todos.
            const desde = entre(0, pacientes.length - 1);
            const paciente = [...pacientes.slice(desde), ...pacientes.slice(0, desde)].find((pa) =>
              !(ocupacionPaciente.get(pa.id) ?? []).some(([a, b]) => seSolapan(t, finCita, a, b)));
            if (!paciente) {
              t += 15 * MIN;
              continue;
            }

            const estado = estadoSegunFecha(t < hoy.getTime(), azar());
            const creada_en = t - entre(1, 10) * DIA;
            const cancelada = estado === "CANCELADA";
            datos.citas.push({
              id: uuid(),
              clinica_id: cid,
              paciente_id: paciente.id,
              profesional_id: prof.id,
              servicio_id: servicio.id,
              inicio: iso(t),
              fin: iso(finCita),
              estado,
              creada_por: recepcion.id,
              creada_en: iso(creada_en),
              cancelada_por: cancelada ? recepcion.id : null,
              cancelada_en: cancelada ? iso(creada_en + DIA) : null,
              motivo_cancelacion: cancelada ? elegir(MOTIVOS_CANCELACION) : null,
              cita_origen_id: null,
            });
            if (esVigente(estado)) {
              ocupacionPaciente.set(paciente.id, [...(ocupacionPaciente.get(paciente.id) ?? []), [t, finCita]]);
            }
            t = finCita;
          }
        }
      }
    });
  }

  return datos;
}

// Pasadas: casi todas atendidas, algunas ausencias y cancelaciones. Futuras: reservadas o canceladas.
function estadoSegunFecha(pasada: boolean, r: number): EstadoCita {
  if (!pasada) return r < 0.88 ? "RESERVADA" : "CANCELADA";
  if (r < 0.75) return "ATENDIDA";
  return r < 0.87 ? "AUSENTE" : "CANCELADA";
}

/** Autoverificación de la semilla: I1 e I2 sobre las citas vigentes. Corre en desarrollo. */
export function verificarSemilla(d: Datos) {
  const vigentes = d.citas.filter((c) => esVigente(c.estado));
  const choca = (clave: (c: Cita) => string) =>
    vigentes.some((a, i) => vigentes.slice(i + 1).some((b) =>
      clave(a) === clave(b) && seSolapan(Date.parse(a.inicio), Date.parse(a.fin), Date.parse(b.inicio), Date.parse(b.fin))));
  console.assert(!choca((c) => c.profesional_id), "Semilla viola I1: profesional con citas solapadas");
  console.assert(!choca((c) => c.paciente_id), "Semilla viola I2: paciente con citas solapadas");
  console.assert(d.clinicas.length >= 3, "La semilla debe tener al menos tres clínicas");
}
