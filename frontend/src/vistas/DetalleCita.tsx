import { useEffect, useRef, useState } from "react";
import { ApiError, cancelarCita, registrarDesenlace, reprogramarCita, simularReservaAjena, type CitaVista } from "../api";
import { ESTADO_NOMBRE, ROLES_QUE_AGENDAN, ROLES_QUE_REGISTRAN_DESENLACE, type Rol } from "../api/dominio";
import Espacios, { type Espacio } from "../componentes/Espacios";
import { fechaCorta, fechaLocal, hora } from "../fechas";
import "./detalle.css";

type Modo = "detalle" | "cancelar" | "reprogramar";

type Props = Readonly<{
  cita: CitaVista;
  profesional: string;
  /** La cita cae dentro de un bloqueo de agenda (RF6): recepción debe reprogramarla. */
  conflicto: boolean;
  rol: Rol;
  onCerrar: () => void;
  /** Se llama tras un cambio exitoso, para que la agenda se vuelva a consultar. */
  onCambio: (mensaje: string) => void;
}>;

const cuando = (inicio: string, fin: string) => `${fechaCorta(fechaLocal(new Date(inicio)))}, ${hora(inicio)} a ${hora(fin)}`;

export default function DetalleCita({ cita, profesional, conflicto, rol, onCerrar, onCambio }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [modo, setModo] = useState<Modo>("detalle");
  const [motivo, setMotivo] = useState("");
  const [espacio, setEspacio] = useState<Espacio | null>(null);
  const [competencia, setCompetencia] = useState(false);
  const [version, setVersion] = useState(0);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState("");

  // <dialog> nativo: el navegador atrapa el foco, cierra con Escape y devuelve el foco
  // al botón que lo abrió. Por eso no hace falta ninguna librería de modales.
  useEffect(() => {
    if (!ref.current?.open) ref.current?.showModal();
  }, []);

  const reservada = cita.estado === "RESERVADA";
  const puedeAgendar = ROLES_QUE_AGENDAN.includes(rol);
  const puedeDesenlace = ROLES_QUE_REGISTRAN_DESENLACE.includes(rol);
  const yaEmpezo = Date.parse(cita.inicio) <= Date.now(); // RF12
  const duracion = (Date.parse(cita.fin) - Date.parse(cita.inicio)) / 60_000;

  async function ejecutar(accion: () => Promise<unknown>, mensaje: string) {
    setEnviando(true);
    setError("");
    try {
      await accion();
      onCambio(mensaje);
      ref.current?.close();
    } catch (e) {
      const base = e instanceof Error ? e.message : "Error inesperado";
      // Si la reprogramación falla no se tocó nada: la cita original sigue como estaba.
      setError(modo === "reprogramar" ? `${base}. La cita original sigue reservada.` : base);
      // Un 409 significa que el espacio elegido ya no está libre: se descarta y se refrescan los horarios.
      if (e instanceof ApiError && e.status === 409) setEspacio(null);
      setVersion((v) => v + 1);
    } finally {
      setEnviando(false);
    }
  }

  function reprogramar() {
    if (!espacio) return;
    const destino = { profesional_id: espacio.profesional.id, inicio: espacio.inicio };
    const nuevoFin = new Date(Date.parse(espacio.inicio) + duracion * 60_000).toISOString();
    ejecutar(
      async () => {
        if (competencia) simularReservaAjena({ paciente_id: cita.paciente_id, servicio_id: cita.servicio_id, ...destino });
        await reprogramarCita(cita.id, destino);
      },
      `Cita de ${cita.paciente} movida a ${cuando(espacio.inicio, nuevoFin)}, con ${espacio.profesional.nombre}.`,
    );
  }

  const marcar = (desenlace: "ATENDIDA" | "AUSENTE") =>
    ejecutar(() => registrarDesenlace(cita.id, desenlace), `Cita de ${cita.paciente} marcada como ${ESTADO_NOMBRE[desenlace].toLowerCase()}.`);

  return (
    <dialog ref={ref} className="detalle" data-modo={modo} aria-labelledby="detalle-titulo" onClose={onCerrar}>
      <div className="detalle-cuerpo">
        <header className="detalle-head">
          <div>
            <span className="estado-pill" data-estado={cita.estado}>
              {ESTADO_NOMBRE[cita.estado]}
            </span>
            <h2 id="detalle-titulo">{cita.paciente}</h2>
          </div>
          <button type="button" className="btn btn-icon" aria-label="Cerrar" onClick={() => ref.current?.close()}>
            ×
          </button>
        </header>

        <dl className="datos">
          <div>
            <dt>Servicio</dt>
            <dd>
              {cita.servicio} · {duracion} min
            </dd>
          </div>
          <div>
            <dt>Profesional</dt>
            <dd>{profesional}</dd>
          </div>
          <div>
            <dt>Cuándo</dt>
            <dd>{cuando(cita.inicio, cita.fin)}</dd>
          </div>
        </dl>

        {modo === "detalle" && conflicto && (
          <p className="aviso-conflicto" role="note">
            Esta cita cae dentro de un bloqueo de agenda del profesional. Reprográmala a otro espacio (RF6).
          </p>
        )}

        {modo === "detalle" &&
          (reservada ? (
            <>
              {puedeDesenlace && (
                <section className="acciones" aria-labelledby="acc-desenlace">
                  <h3 id="acc-desenlace">Registrar desenlace</h3>
                  <div className="fila">
                    <button type="button" className="btn" disabled={!yaEmpezo || enviando} onClick={() => marcar("ATENDIDA")}>
                      Marcar atendida
                    </button>
                    <button type="button" className="btn" disabled={!yaEmpezo || enviando} onClick={() => marcar("AUSENTE")}>
                      Marcar ausente
                    </button>
                  </div>
                  {!yaEmpezo && <p className="ayuda">Se habilita cuando llegue la hora de inicio de la cita (RF12).</p>}
                </section>
              )}
              {puedeAgendar && (
                <section className="acciones" aria-labelledby="acc-cambiar">
                  <h3 id="acc-cambiar">Cambiar la cita</h3>
                  <div className="fila">
                    <button type="button" className={conflicto ? "btn btn-cta" : "btn"} onClick={() => setModo("reprogramar")}>
                      Reprogramar
                    </button>
                    <button type="button" className="btn btn-peligro" onClick={() => setModo("cancelar")}>
                      Cancelar cita
                    </button>
                  </div>
                </section>
              )}
            </>
          ) : (
            <p className="ayuda">Estado final: la cita ya no admite cambios (RF13).</p>
          ))}

        {modo === "cancelar" && (
          <form
            className="acciones"
            onSubmit={(e) => {
              e.preventDefault();
              ejecutar(() => cancelarCita(cita.id, motivo), `Cita de ${cita.paciente} cancelada. El espacio ya está libre.`);
            }}
          >
            <label className="field">
              <span>Motivo de la cancelación</span>
              <textarea rows={3} required value={motivo} onChange={(e) => setMotivo(e.target.value)} />
            </label>
            <p className="ayuda">Se guardan el motivo, tu usuario y la hora. El espacio queda libre de inmediato (I7).</p>
            <div className="fila">
              <button type="button" className="btn" onClick={() => setModo("detalle")}>
                Volver
              </button>
              <button type="submit" className="btn btn-peligro" disabled={motivo.trim().length < 3 || enviando}>
                {enviando ? "Cancelando…" : "Confirmar cancelación"}
              </button>
            </div>
          </form>
        )}

        {modo === "reprogramar" && (
          <section className="acciones" aria-label="Reprogramar">
            <p className="ayuda">
              El servicio y su duración ({duracion} min) no cambian (I4). La cita actual se libera en el mismo momento en que se confirma
              la nueva.
            </p>
            <label className="demo">
              <input type="checkbox" checked={competencia} onChange={(e) => setCompetencia(e.target.checked)} />
              <span>
                <strong>Simular otra recepcionista</strong>
                Demostración: alguien toma el espacio nuevo justo antes de que confirmes. La cita original debe quedar intacta.
              </span>
            </label>

            <Espacios servicioId={cita.servicio_id} ignorarCitaId={cita.id} elegido={espacio} onElegir={setEspacio} version={version} />

          </section>
        )}

        {/* Barra fija abajo: el resumen, el error y la confirmación siempre quedan a la vista aunque la lista de horarios sea larga. */}
        {(modo === "reprogramar" || error) && (
          <footer className="pie">
            {modo === "reprogramar" && espacio && (
              <p className="mover">
                <span>{cuando(cita.inicio, cita.fin)}</span>
                <span aria-hidden="true">→</span>
                <strong>
                  {fechaCorta(fechaLocal(new Date(espacio.inicio)))}, {hora(espacio.inicio)} con {espacio.profesional.nombre}
                </strong>
              </p>
            )}
            {error && (
              <p className="aviso aviso-error" role="alert">
                {error}
              </p>
            )}
            {modo === "reprogramar" && (
              <div className="fila">
                <button type="button" className="btn" onClick={() => setModo("detalle")}>
                  Volver
                </button>
                <button type="button" className="btn btn-cta" disabled={!espacio || enviando} onClick={reprogramar}>
                  {enviando ? "Moviendo…" : "Mover cita"}
                </button>
              </div>
            )}
          </footer>
        )}
      </div>
    </dialog>
  );
}
