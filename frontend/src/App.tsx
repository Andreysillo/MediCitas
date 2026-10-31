import { lazy, Suspense, useEffect, type ComponentType } from "react";
import type { Sesion } from "./api";
import Entrar from "./Entrar";
import { ROL_NOMBRE, rutasDe } from "./navigation";
import { navegar, useRuta } from "./router";
import { salir, useSesion } from "./sesion";
import Agenda from "./vistas/Agenda";
import Bitacora from "./vistas/Bitacora";
import Catalogo from "./vistas/Catalogo";
import Clinicas from "./vistas/Clinicas";
import Horarios from "./vistas/Horarios";
import Pacientes from "./vistas/Pacientes";
import Reportes from "./vistas/Reportes";
import Reservar from "./vistas/Reservar";
import Usuarios from "./vistas/Usuarios";

// Vista de cada ruta. Las que aún no existen muestran el aviso de "próximamente".
const VISTAS: Partial<Record<string, ComponentType<{ sesion: Sesion }>>> = {
  "/agenda": Agenda,
  "/reservar": Reservar,
  "/pacientes": Pacientes,
  "/horarios": Horarios,
  "/catalogo": Catalogo,
  "/usuarios": Usuarios,
  "/reportes": Reportes,
  "/bitacora": Bitacora,
  "/clinicas": Clinicas,
};

// La landing (con GSAP y WebGL) va en su propio archivo: la aplicación no descarga esas librerías.
const Landing = lazy(() => import("./Landing"));

// "#/" (o sin hash) es la landing pública y "#/entrar" el ingreso. El resto es la aplicación,
// que exige sesión: sin ella se muestra el ingreso (con Keycloak, la redirección a su login).
export default function App() {
  const ruta = useRuta();
  const sesion = useSesion();
  let pantalla: "landing" | "entrar" | "app" = "app";
  if (ruta === "/") pantalla = "landing";
  else if (ruta === "/entrar" || !sesion) pantalla = "entrar";

  // Al pasar de una pantalla a otra se empieza arriba, no a media página.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pantalla]);

  if (pantalla === "landing") {
    return (
      <Suspense>
        <Landing />
      </Suspense>
    );
  }
  if (pantalla === "entrar" || !sesion) return <Entrar />;
  return <Aplicacion sesion={sesion} ruta={ruta} />;
}

// La ruta llega desde App y no de un useRuta propio: con dos suscripciones al hash, la de este componente
// se procesaba primero y su redirección (abajo) devolvía a la agenda antes de que App mostrara /entrar o /.
function Aplicacion({ sesion, ruta }: Readonly<{ sesion: Sesion; ruta: string }>) {
  const rol = sesion.usuario.rol;
  const rutas = rutasDe(rol);
  const actual = rutas.find((r) => r.path === ruta);
  const Vista = actual && VISTAS[actual.path];

  // Si la ruta no existe o el rol no la tiene, se va a la primera permitida.
  useEffect(() => {
    if (!actual) navegar(rutas[0].path);
  }, [actual, rutas]);

  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#/" title="Ir a la página de inicio">
          Medi<span>Citas</span>
        </a>

        <nav className="nav" aria-label="Principal">
          {rutas.map((r) => (
            <a key={r.path} href={`#${r.path}`} aria-current={r === actual ? "page" : undefined}>
              {r.titulo}
            </a>
          ))}
        </nav>

        <div className="session">
          <div className="session-who">
            <strong>{sesion.usuario.nombre}</strong>
            <span>{ROL_NOMBRE[rol]}</span>
            <span>{sesion.clinica?.nombre ?? "Plataforma MediCitas"}</span>
          </div>
          <div className="session-acciones">
            <a className="btn" href="#/entrar">
              Cambiar de rol
            </a>
            {/* Primero la ruta y luego la sesión: al redibujar ya se está en la landing, no en el ingreso. */}
            <button
              type="button"
              className="btn"
              onClick={() => {
                navegar("/");
                salir();
              }}
            >
              Salir
            </button>
          </div>
        </div>
      </aside>

      <main className="main">
        {actual && (
          <>
            <header className="page-head">
              <span className="eyebrow">
                {ROL_NOMBRE[rol]}
                {sesion.clinica && ` · ${sesion.clinica.nombre}`}
              </span>
              <h1>{actual.titulo}</h1>
              <p>{actual.descripcion}</p>
            </header>
            {/* key: al cambiar de usuario la vista se monta de nuevo y no arrastra datos de otra clínica. */}
            {Vista ? (
              <Vista key={sesion.usuario.id} sesion={sesion} />
            ) : (
              <div className="placeholder">Esta vista se construye en los siguientes avances.</div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
