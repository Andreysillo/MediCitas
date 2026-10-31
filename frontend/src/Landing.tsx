import { useEffect, useRef, type ComponentType, type CSSProperties } from "react";
import FoldText from "./componentes/FoldText";
import WarpText from "./componentes/WarpText";
import "./landing.css";

// Página pública que presenta MediCitas (producto ficticio del curso). En el hero, el nombre se deforma
// como vidrio bajo el cursor (WarpText) y un aura de color lo sigue; los títulos se despliegan como papel
// (FoldText) y cada función es una tarjeta que se apila sobre la anterior al bajar (CSS sticky).

/** Turno de entrada en el hero: cada elemento aparece 70 ms después del anterior. */
const orden = (i: number) => ({ "--i": i }) as CSSProperties;

function Isotipo({ className }: Readonly<{ className?: string }>) {
  return (
    <svg className={className} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="9" />
      <path d="M13 8h6v5h5v6h-5v5h-6v-5H8v-6h5z" />
    </svg>
  );
}

// ---------- Maquetas de cada función (datos ficticios, con los nombres de la demo) ----------

const AGENDA = [
  { hora: "08:00", paciente: "Ana Granados", servicio: "Consulta general", estado: "ATENDIDA", texto: "Atendida" },
  { hora: "08:20", paciente: "Tomás Salazar", servicio: "Certificado médico", estado: "ATENDIDA", texto: "Atendida" },
  { hora: "09:00", paciente: "María Calderón", servicio: "Control de niño sano", estado: "RESERVADA", texto: "Reservada" },
  { hora: "09:30", paciente: "José Villalobos", servicio: "Limpieza dental", estado: "RESERVADA", texto: "Reservada" },
];

function MockAgenda() {
  return (
    <figure className="muestra">
      <figcaption>
        <span>Hoy · Clínica San Rafael</span>
        <span>Dra. Laura Méndez</span>
      </figcaption>
      <ol>
        {AGENDA.map((c) => (
          <li key={c.hora} data-estado={c.estado}>
            <time>{c.hora}</time>
            <span>
              <strong>{c.paciente}</strong>
              {c.servicio}
            </span>
            <em>{c.texto}</em>
          </li>
        ))}
        <li className="muestra-libre">
          <time>10:10</time>
          <span>Espacio libre</span>
        </li>
      </ol>
    </figure>
  );
}

const ESPACIOS = [
  { hora: "08:00", estado: "tomado" },
  { hora: "08:20", estado: "libre" },
  { hora: "08:40", estado: "tomado" },
  { hora: "09:00", estado: "elegido" },
  { hora: "09:20", estado: "libre" },
  { hora: "09:40", estado: "libre" },
  { hora: "10:00", estado: "tomado" },
  { hora: "10:20", estado: "libre" },
];

function MockReserva() {
  return (
    <figure className="muestra">
      <figcaption>
        <span>Consulta general · 20 min</span>
        <span>Dr. Carlos Jiménez</span>
      </figcaption>
      <ul className="m-espacios">
        {ESPACIOS.map((e) => (
          <li key={e.hora} data-estado={e.estado}>
            {e.hora}
          </li>
        ))}
      </ul>
      <p className="muestra-nota">Otra persona tomó las 08:40 hace un instante. Elige otro espacio.</p>
    </figure>
  );
}

function MockNota() {
  return (
    <figure className="muestra">
      <figcaption>
        <span>Nota clínica · Ana Granados</span>
        <span>Privada</span>
      </figcaption>
      <div className="m-nota">
        <p>Motivo: control de presión arterial.</p>
        <p>PA 128/82 mmHg. Sin síntomas nuevos.</p>
        <p>Plan: continuar tratamiento y control en tres meses.</p>
      </div>
      <ul className="m-permisos">
        <li data-puede="si">Dra. Laura Méndez · lee y edita</li>
        <li data-puede="no">Recepción · sin acceso</li>
      </ul>
    </figure>
  );
}

const BITACORA = [
  { hora: "09:02", quien: "Dra. Laura Méndez", accion: "Editó", recurso: "Nota · Ana Granados" },
  { hora: "08:57", quien: "Daniela Chaves", accion: "Leyó", recurso: "Ficha · María Calderón" },
  { hora: "08:41", quien: "Dra. Laura Méndez", accion: "Leyó", recurso: "Nota · Ana Granados" },
  { hora: "08:15", quien: "Marta Solís", accion: "Leyó", recurso: "Ficha · Tomás Salazar" },
];

function MockBitacora() {
  return (
    <figure className="muestra">
      <figcaption>
        <span>Bitácora · hoy</span>
        <span>Solo agregar</span>
      </figcaption>
      <ol className="m-bitacora">
        {BITACORA.map((r) => (
          <li key={r.hora}>
            <time>{r.hora}</time>
            <span>
              <strong>{r.quien}</strong>
              {r.recurso}
            </span>
            <em>{r.accion}</em>
          </li>
        ))}
      </ol>
    </figure>
  );
}

const CLINICAS = [
  { nombre: "Clínica San Rafael", id: "san-rafael", propia: true },
  { nombre: "Centro Médico del Valle", id: "del-valle", propia: false },
  { nombre: "Clínica Los Robles", id: "los-robles", propia: false },
];

function MockClinicas() {
  return (
    <figure className="muestra">
      <figcaption>
        <span>Sesión · Daniela Chaves</span>
        <span>Recepción</span>
      </figcaption>
      <ul className="m-clinicas">
        {CLINICAS.map((c) => (
          <li key={c.id} data-propia={c.propia}>
            <span>
              <strong>{c.nombre}</strong>
              {c.id}
            </span>
            <em>{c.propia ? "Su clínica" : "Sin acceso"}</em>
          </li>
        ))}
      </ul>
    </figure>
  );
}

const REPORTE = [
  { estado: "ATENDIDA", texto: "Atendidas", pct: 64 },
  { estado: "RESERVADA", texto: "Reservadas", pct: 18 },
  { estado: "AUSENTE", texto: "Ausentes", pct: 9 },
  { estado: "CANCELADA", texto: "Canceladas", pct: 6 },
  { estado: "REPROGRAMADA", texto: "Reprogramadas", pct: 3 },
];

function MockReporte() {
  return (
    <figure className="muestra">
      <figcaption>
        <span>Citas por estado</span>
        <span>Últimos 14 días</span>
      </figcaption>
      <ul className="m-reporte">
        {REPORTE.map((r) => (
          <li key={r.estado} data-estado={r.estado}>
            <span>{r.texto}</span>
            <span className="m-barra" style={{ "--pct": `${r.pct}%` } as CSSProperties} />
            <time>{r.pct}%</time>
          </li>
        ))}
      </ul>
    </figure>
  );
}

const FUNCIONES: { titulo: string; texto: string; Mock: ComponentType }[] = [
  {
    titulo: "Agenda del día",
    texto: "Por profesional o de toda la clínica. Cada cita con su estado, de un vistazo.",
    Mock: MockAgenda,
  },
  {
    titulo: "Reservas sin choques",
    texto: "Solo se ofrecen horas libres. Si alguien toma el mismo espacio un segundo antes, la base de datos lo impide y se avisa.",
    Mock: MockReserva,
  },
  {
    titulo: "Notas clínicas privadas",
    texto: "La nota pertenece a quien atiende. Recepción agenda sin ver diagnósticos.",
    Mock: MockNota,
  },
  {
    titulo: "Bitácora que no se borra",
    texto: "Cada lectura y cada cambio de una ficha queda registrado: quién, qué y cuándo. Nada se edita ni se elimina.",
    Mock: MockBitacora,
  },
  {
    titulo: "Cada clínica en su casa",
    texto: "Una sola plataforma, datos separados. Ninguna clínica ve pacientes, citas ni usuarios de otra.",
    Mock: MockClinicas,
  },
  {
    titulo: "Reportes al día",
    texto: "Citas por estado en cualquier rango de fechas: cuántas se atendieron y cuántas se perdieron.",
    Mock: MockReporte,
  },
];

const ROLES = [
  { nombre: "Recepción", texto: "Reserva en tres pasos, reprograma y cancela sin perder el historial." },
  { nombre: "Profesional", texto: "Su agenda del día, el desenlace de cada cita y sus notas privadas." },
  { nombre: "Administración", texto: "Horarios, bloqueos, catálogo, usuarios, reportes y bitácora." },
  { nombre: "Plataforma", texto: "Da de alta clínicas nuevas junto con su primer administrador." },
];

const SECCIONES = [
  { id: "l-inicio", nombre: "Inicio" },
  { id: "l-funciones", nombre: "Funciones" },
  { id: "l-roles", nombre: "Para cada rol" },
  { id: "l-prueba", nombre: "Probar la demo" },
];

// Las rutas son hash (#/agenda), así que el menú no usa anclas #seccion: cierra el popover y desplaza.
function irA(id: string) {
  document.getElementById("l-menu")?.hidePopover();
  document.getElementById(id)?.scrollIntoView();
}

/** FoldText toma tamaño y peso del título que lo contiene. */
const HEREDA = { fontSize: "inherit", fontWeight: "inherit" } as const;

/** Título de sección que se despliega como papel al entrar en pantalla; `acento` es la parte en itálica. */
function Pliegue({ texto, acento = false }: Readonly<{ texto: string; acento?: boolean }>) {
  const pliegue = <FoldText text={texto} trigger="scroll" stagger={0.025} {...HEREDA} />;
  return acento ? <em>{pliegue}</em> : pliegue;
}

export default function Landing() {
  const aura = useRef<HTMLDivElement>(null);

  // El aura sigue al puntero solo con mouse y sin movimiento reducido. Se mueve con transform
  // (sin re-render de React) y una transición CSS le da el retraso suave.
  useEffect(() => {
    const el = aura.current;
    if (!el || !matchMedia("(hover: hover) and (prefers-reduced-motion: no-preference)").matches) return;
    let cuadro = 0;
    const mover = (e: PointerEvent) => {
      cancelAnimationFrame(cuadro);
      cuadro = requestAnimationFrame(() => {
        const caja = el.parentElement!.getBoundingClientRect();
        el.style.transform = `translate3d(${e.clientX - caja.left}px, ${e.clientY - caja.top}px, 0)`;
      });
    };
    document.addEventListener("pointermove", mover);
    return () => {
      document.removeEventListener("pointermove", mover);
      cancelAnimationFrame(cuadro);
    };
  }, []);

  return (
    <div className="landing">
      <section id="l-inicio" className="hero" aria-labelledby="l-titulo">
        <div className="hero-aura" ref={aura} aria-hidden="true" />

        <header className="l-top">
          <Isotipo className="l-isotipo" />
          {/* Menú con popover nativo: el navegador maneja Esc, el clic afuera y aria-expanded. */}
          <button type="button" className="btn btn-claro" popoverTarget="l-menu">
            Menú
          </button>
          <nav id="l-menu" className="l-menu" popover="auto" aria-label="Secciones de la página">
            <ol>
              {SECCIONES.map((s, i) => (
                <li key={s.id}>
                  <button type="button" onClick={() => irA(s.id)}>
                    <span>0{i + 1}</span>
                    {s.nombre}
                  </button>
                </li>
              ))}
            </ol>
            <a className="btn btn-blanco btn-bloque" href="#/entrar">
              Entrar a la demo
            </a>
          </nav>
        </header>

        <div className="hero-cuerpo">
          <h1 id="l-titulo" className="hero-marca">
            <WarpText
              text="MediCitas"
              acento={{ desde: 4, color: "#7dd3fc" }}
              fontSize="clamp(4rem, 14vw, 12rem)"
              fontWeight={700}
              letterSpacing="-0.06em"
              chromatic={0.35}
              idleDrift={0.2}
            />
          </h1>
          <p className="hero-eslogan">
            <FoldText text="Tus servicios médicos, a tu alcance." hinge="bottom" stagger={0.025} {...HEREDA} />
          </p>
          <div className="hero-acciones entra" style={orden(4)}>
            <a className="btn btn-blanco" href="#/entrar">
              Probar la demo
            </a>
          </div>
        </div>
      </section>

      <section id="l-funciones" className="vitrina" aria-labelledby="l-func-t">
        <div className="vitrina-cabeza">
          <p className="l-eyebrow">Funciones</p>
          <h2 id="l-func-t">
            <Pliegue texto="Todo lo que pasa en tu clínica," /> <Pliegue texto="en un solo lugar." acento />
          </h2>
        </div>
        <ol className="escenas">
          {FUNCIONES.map(({ titulo, texto, Mock }, i) => (
            <li key={titulo} className="escena" style={orden(i)}>
              <div className="escena-texto">
                <span className="escena-n">/ 0{i + 1}</span>
                <h3>{titulo}</h3>
                <p>{texto}</p>
              </div>
              <Mock />
            </li>
          ))}
        </ol>
      </section>

      <section id="l-roles" className="l-seccion" aria-labelledby="l-roles-t">
        <p className="l-eyebrow">Para cada rol</p>
        <h2 id="l-roles-t">
          <Pliegue texto="Una plataforma," /> <Pliegue texto="cuatro miradas." acento />
        </h2>
        <ul className="roles">
          {ROLES.map((r) => (
            <li key={r.nombre} className="revela">
              <span className="rol-nombre">{r.nombre}</span>
              <p>{r.texto}</p>
            </li>
          ))}
        </ul>
      </section>

      <footer id="l-prueba" className="cierre">
        <div className="cierre-cta">
          <h2>
            <Pliegue texto="Pruébala con" /> <Pliegue texto="datos ficticios." acento />
          </h2>
          <p className="revela">
            Tres clínicas de ejemplo con sus profesionales y semanas de citas. Elige con qué rol entrar y cámbialo
            cuando quieras.
          </p>
          <a className="btn btn-blanco revela" href="#/entrar">
            Entrar a la demo
          </a>
        </div>
        <p className="cierre-marca" aria-hidden="true">
          MediCitas
        </p>
        <p className="cierre-legal">MediCitas es un producto ficticio · Proyecto de Bases de Datos 3, TEC · 2026</p>
      </footer>
    </div>
  );
}
