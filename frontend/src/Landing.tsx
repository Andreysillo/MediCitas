import { useEffect, useRef, type CSSProperties } from "react";
import "./landing.css";

// Página pública que presenta MediCitas (producto ficticio del curso). Su única idea expresiva:
// un aura de color que sigue al cursor en el hero. El resto aparece con el scroll, solo con CSS.

const PASOS = [
  { titulo: "Servicio", texto: "Su duración define cuánto espacio ocupa la cita." },
  { titulo: "Espacio", texto: "Solo se ofrecen horas libres según el horario y los bloqueos del profesional." },
  { titulo: "Paciente", texto: "Se confirma. Si alguien tomó ese espacio un segundo antes, se avisa y nada se duplica." },
];

const FUNCIONES = [
  { titulo: "Agenda sin choques", texto: "Dos citas no pueden ocupar el mismo espacio de un profesional. Lo impide la base de datos, no solo la pantalla." },
  { titulo: "Cada clínica en su casa", texto: "Una sola plataforma, datos separados. Ninguna clínica ve pacientes, citas ni usuarios de otra." },
  { titulo: "Notas que solo lee quien atiende", texto: "La nota clínica pertenece al profesional. Recepción agenda sin ver diagnósticos." },
  { titulo: "Bitácora que no se borra", texto: "Quién abrió qué ficha y cuándo. Los registros se agregan; nunca se editan ni se eliminan." },
];

const ROLES = [
  { nombre: "Recepción", texto: "Reserva en tres pasos, reprograma y cancela sin perder el historial." },
  { nombre: "Profesional", texto: "Su agenda del día, el desenlace de cada cita y sus notas privadas." },
  { nombre: "Administración", texto: "Horarios, bloqueos, catálogo, usuarios, reportes y bitácora." },
  { nombre: "Plataforma", texto: "Da de alta clínicas nuevas junto con su primer administrador." },
];

const MUESTRA = [
  { hora: "08:00", paciente: "Ana Granados", servicio: "Consulta general", estado: "ATENDIDA", texto: "Atendida" },
  { hora: "08:20", paciente: "Tomás Salazar", servicio: "Certificado médico", estado: "ATENDIDA", texto: "Atendida" },
  { hora: "09:00", paciente: "María Calderón", servicio: "Control de niño sano", estado: "RESERVADA", texto: "Reservada" },
  { hora: "09:30", paciente: "José Villalobos", servicio: "Limpieza dental", estado: "RESERVADA", texto: "Reservada" },
];

/** Turno de entrada en el hero: cada elemento aparece 70 ms después del anterior. */
const orden = (i: number) => ({ "--i": i }) as CSSProperties;

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
      <section className="hero" aria-labelledby="l-titulo">
        <div className="hero-aura" ref={aura} aria-hidden="true" />

        <header className="l-top">
          <span className="l-marca">
            Medi<span>Citas</span>
          </span>
          <a className="btn btn-claro" href="#/agenda">
            Entrar a la demo
          </a>
        </header>

        <div className="hero-cuerpo">
          <div className="hero-texto">
            <p className="l-eyebrow entra" style={orden(0)}>
              Agenda clínica para equipos pequeños y medianos
            </p>
            <h1 id="l-titulo" className="entra" style={orden(1)}>
              Cada cita, <em>en su lugar.</em>
            </h1>
            <p className="hero-sub entra" style={orden(2)}>
              MediCitas ordena la agenda de tu clínica: reservas sin choques, notas que solo ve quien atiende y una
              bitácora que responde quién vio qué.
            </p>
            <div className="hero-acciones entra" style={orden(3)}>
              <a className="btn btn-cta" href="#/agenda">
                Probar la demo
              </a>
              <button
                type="button"
                className="btn btn-claro"
                onClick={() => document.getElementById("l-como")?.scrollIntoView()}
              >
                Cómo funciona
              </button>
            </div>
          </div>

          <figure className="muestra entra" style={orden(2)}>
            <figcaption>
              <span>Hoy · Clínica San Rafael</span>
              <span>Dra. Laura Méndez</span>
            </figcaption>
            <ol>
              {MUESTRA.map((c) => (
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
            <p className="muestra-nota">Nota clínica privada · solo la profesional</p>
          </figure>
        </div>
      </section>

      <section id="l-como" className="l-seccion" aria-labelledby="l-como-t">
        <p className="l-eyebrow">Cómo funciona</p>
        <h2 id="l-como-t" className="revela">
          Reservar toma <em>tres decisiones.</em>
        </h2>
        <ol className="pasos">
          {PASOS.map((p, i) => (
            <li key={p.titulo} className="revela">
              <span className="pasos-n">0{i + 1}</span>
              <h3>{p.titulo}</h3>
              <p>{p.texto}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="l-seccion" aria-labelledby="l-func-t">
        <p className="l-eyebrow">Lo esencial</p>
        <h2 id="l-func-t" className="revela">
          Lo que una clínica <em>no deja al azar.</em>
        </h2>
        <ul className="funciones">
          {FUNCIONES.map((f, i) => (
            <li key={f.titulo} className="funcion revela">
              <span className="funcion-n">/ 0{i + 1}</span>
              <h3>{f.titulo}</h3>
              <p>{f.texto}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="l-seccion" aria-labelledby="l-roles-t">
        <p className="l-eyebrow">Para cada rol</p>
        <h2 id="l-roles-t" className="revela">
          Una plataforma, <em>cuatro miradas.</em>
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

      <footer className="cierre">
        <div className="cierre-cta">
          <h2 className="revela">
            Pruébala con <em>datos ficticios.</em>
          </h2>
          <p className="revela">
            Tres clínicas de ejemplo con sus profesionales y semanas de citas. Cambia de usuario cuando quieras con
            "Ver como".
          </p>
          <a className="btn btn-cta revela" href="#/agenda">
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
