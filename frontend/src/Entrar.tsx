import { useEffect, useMemo, useRef, useState } from "react";
import { usuariosDePrueba } from "./api";
import type { Rol } from "./api/dominio";
import { mensajeDe } from "./hooks";
import { ROL_NOMBRE, rutasDe } from "./navigation";
import { navegar } from "./router";
import { entrarComo } from "./sesion";
import "./entrar.css";

// Ingreso a la demo en tres pasos: rol, clínica y usuario de prueba. Con Keycloak esta pantalla
// se reemplaza por su login, que ya sabe la clínica y el rol de cada persona.

const ROLES: readonly { rol: Rol; texto: string }[] = [
  { rol: "RECEPCION", texto: "Reserva, reprograma y cancela citas, y registra pacientes." },
  { rol: "PROFESIONAL", texto: "Su agenda, el desenlace de sus citas y sus notas clínicas privadas." },
  { rol: "ADM_CLINICA", texto: "Horarios, catálogo, usuarios, reportes y la bitácora de su clínica." },
  { rol: "ADM_PLATAFORMA", texto: "Da de alta clínicas nuevas. No ve datos clínicos de ninguna." },
];

const iniciales = (nombre: string) =>
  nombre
    .replace(/^(Dra?\.)\s+/, "")
    .split(" ")
    .slice(0, 2)
    .map((p) => p[0])
    .join("");

function cuantos(n: number) {
  if (n === 0) return "Sin usuarios con este rol";
  return n === 1 ? "1 usuario de prueba" : `${n} usuarios de prueba`;
}

export default function Entrar() {
  const grupos = useMemo(usuariosDePrueba, []);
  const [rol, setRol] = useState<Rol | null>(null);
  const [clinicaId, setClinicaId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const titulo = useRef<HTMLHeadingElement>(null);

  const plataforma = rol === "ADM_PLATAFORMA";
  let paso = 3;
  if (!rol) paso = 1;
  else if (!plataforma && !clinicaId) paso = 2;
  // La plataforma no pertenece a ninguna clínica: se salta ese paso.
  const total = plataforma ? 2 : 3;
  const numero = plataforma && paso === 3 ? 2 : paso;

  const deEseRol = (g: (typeof grupos)[number]) => g.usuarios.filter((u) => u.rol === rol);
  const grupo = grupos.find((g) => g.clinicaId === (plataforma ? null : clinicaId));

  // Al cambiar de paso, el foco va al nuevo título: el lector de pantalla anuncia la pregunta.
  useEffect(() => {
    if (paso > 1) titulo.current?.focus();
  }, [paso]);

  const atras = () => {
    setError("");
    if (paso === 3 && !plataforma) setClinicaId(null);
    else setRol(null);
  };

  const entrar = (usuarioId: string) => {
    try {
      const sesion = entrarComo(usuarioId);
      navegar(rutasDe(sesion.usuario.rol)[0].path);
    } catch (e) {
      setError(mensajeDe(e));
    }
  };

  return (
    <div className="entrar">
      <header className="e-top">
        <a className="e-marca" href="#/">
          Medi<span>Citas</span>
        </a>
        <span className="e-progreso" aria-live="polite">
          Paso {numero} de {total}
        </span>
      </header>

      <main className="e-cuerpo" key={paso}>
        {paso > 1 && (
          <button type="button" className="btn e-atras" onClick={atras}>
            ← Atrás
          </button>
        )}

        {paso === 1 && (
          <>
            <h1 ref={titulo} tabIndex={-1}>
              ¿Cómo quieres <em>entrar?</em>
            </h1>
            <p className="e-ayuda">Elige un rol de prueba. Dentro verás solo lo que ese rol tiene permitido.</p>
            <ul className="e-opciones">
              {ROLES.map((r, i) => (
                <li key={r.rol}>
                  <button type="button" className="e-opcion" onClick={() => setRol(r.rol)}>
                    <span className="e-n">/ 0{i + 1}</span>
                    <strong>{ROL_NOMBRE[r.rol]}</strong>
                    <span className="e-texto">{r.texto}</span>
                    <span className="e-puede">{rutasDe(r.rol).map((ruta) => ruta.titulo).join(" · ")}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}

        {paso === 2 && rol && (
          <>
            <h1 ref={titulo} tabIndex={-1}>
              ¿En qué <em>clínica?</em>
            </h1>
            <p className="e-ayuda">{ROL_NOMBRE[rol]}: solo verás los datos de la clínica que elijas.</p>
            <ul className="e-opciones">
              {grupos
                .filter((g) => g.clinicaId)
                .map((g) => {
                  const n = deEseRol(g).length;
                  return (
                    <li key={g.clinicaId}>
                      <button type="button" className="e-opcion" disabled={n === 0} onClick={() => setClinicaId(g.clinicaId)}>
                        <strong>{g.etiqueta}</strong>
                        <span className="e-texto">{cuantos(n)}</span>
                      </button>
                    </li>
                  );
                })}
            </ul>
          </>
        )}

        {paso === 3 && rol && grupo && (
          <>
            <h1 ref={titulo} tabIndex={-1}>
              ¿Quién <em>eres?</em>
            </h1>
            <p className="e-ayuda">
              {ROL_NOMBRE[rol]} · {grupo.etiqueta}
            </p>
            {error && (
              <p className="aviso aviso-error" role="alert">
                {error}
              </p>
            )}
            <ul className="e-opciones e-personas">
              {deEseRol(grupo).map((u) => (
                <li key={u.id}>
                  <button type="button" className="e-opcion e-persona" onClick={() => entrar(u.id)}>
                    <span className="e-inicial" aria-hidden="true">
                      {iniciales(u.nombre)}
                    </span>
                    <strong>{u.nombre}</strong>
                    <span className="e-ir">Entrar →</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </main>
    </div>
  );
}
