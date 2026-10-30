import { useEffect, useState, type ComponentType } from "react";
import { iniciarSesion, usuariosDePrueba, type Sesion } from "./api";
import { ROL_NOMBRE, rutasDe } from "./navigation";
import { navegar, useRuta } from "./router";
import Agenda from "./vistas/Agenda";
import Pacientes from "./vistas/Pacientes";
import Reservar from "./vistas/Reservar";

// Vista de cada ruta. Las que aún no existen muestran el aviso de "próximamente".
const VISTAS: Partial<Record<string, ComponentType<{ sesion: Sesion }>>> = {
  "/agenda": Agenda,
  "/reservar": Reservar,
  "/pacientes": Pacientes,
};

const GRUPOS = usuariosDePrueba();
const RECEPCION_INICIAL = GRUPOS[1].usuarios.find((u) => u.rol === "RECEPCION")!;

export default function App() {
  // Provisional: se elige el usuario a mano hasta conectar Keycloak, que traerá clínica y rol en el token.
  const [sesion, setSesion] = useState(() => iniciarSesion(RECEPCION_INICIAL.id));
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
        <a className="brand" href={`#${rutas[0].path}`}>
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
            {GRUPOS.map((g) => (
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
