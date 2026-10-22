import { useEffect, useState } from "react";
import { ROL_NOMBRE, rutasDe, type Rol } from "./navigation";
import { navegar, useRuta } from "./router";

const ROLES = Object.keys(ROL_NOMBRE) as Rol[];

export default function App() {
  // Provisional: el rol se elige a mano hasta conectar Keycloak, que lo traerá en el token.
  const [rol, setRol] = useState<Rol>("RECEPCION");
  const ruta = useRuta();
  const rutas = rutasDe(rol);
  const actual = rutas.find((r) => r.path === ruta);

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
          <label htmlFor="rol">Ver como</label>
          <select id="rol" value={rol} onChange={(e) => setRol(e.target.value as Rol)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROL_NOMBRE[r]}
              </option>
            ))}
          </select>
        </div>
      </aside>

      <main className="main">
        {actual && (
          <>
            <header className="page-head">
              <span className="eyebrow">{ROL_NOMBRE[rol]}</span>
              <h1>{actual.titulo}</h1>
              <p>{actual.descripcion}</p>
            </header>
            <div className="placeholder">Esta vista se construye en los siguientes avances.</div>
          </>
        )}
      </main>
    </div>
  );
}
