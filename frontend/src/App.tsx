import { lazy, Suspense, useEffect, useState, useSyncExternalStore, type ComponentType } from "react";
import { iniciarSesion, suscribirUsuarios, usuariosDePrueba, versionDeUsuarios, type Sesion } from "./api";
import { ROL_NOMBRE, rutasDe } from "./navigation";
import { navegar, useRuta } from "./router";
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

const RECEPCION_INICIAL = usuariosDePrueba()[1].usuarios.find((u) => u.rol === "RECEPCION")!;

// "#/" (o sin hash) es la landing pública; cualquier otra ruta es la aplicación.
export default function App() {
  const enLanding = useRuta() === "/";
  // Al pasar de una a otra se empieza arriba, no a media página.
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [enLanding]);
  return enLanding ? (
    <Suspense>
      <Landing />
    </Suspense>
  ) : (
    <Aplicacion />
  );
}

function Aplicacion() {
  // Provisional: se elige el usuario a mano hasta conectar Keycloak, que traerá clínica y rol en el token.
  const [sesion, setSesion] = useState(() => iniciarSesion(RECEPCION_INICIAL.id));
  // El selector se vuelve a armar cuando se crean o dan de baja usuarios o clínicas.
  useSyncExternalStore(suscribirUsuarios, versionDeUsuarios);
  const grupos = usuariosDePrueba();
  const rol = sesion.usuario.rol;
  const ruta = useRuta();
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
            <span>{sesion.clinica?.nombre ?? "Plataforma MediCitas"}</span>
          </div>
          <label htmlFor="usuario">Ver como</label>
          <select id="usuario" value={sesion.usuario.id} onChange={(e) => setSesion(iniciarSesion(e.target.value))}>
            {grupos.map((g) => (
              <optgroup key={g.etiqueta} label={g.etiqueta}>
                {g.usuarios.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.nombre} · {ROL_NOMBRE[u.rol]}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
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
