import { useState } from "react";
import { guardarNota, obtenerNota } from "../api";
import { fechaCompleta, fechaLocal, hora } from "../fechas";

const MAX = 5000;

type Props = Readonly<{
  citaId: string;
  /** La cita ya tiene una nota guardada (el contenido no viaja hasta que el profesional la abre). */
  tieneNota: boolean;
  onGuardada: () => void;
}>;

/** Nota clínica de una cita atendida (RF15). Solo la ve y la escribe el profesional de esa cita. */
export default function EditorNota({ citaId, tieneNota, onGuardada }: Props) {
  const [existe, setExiste] = useState(tieneNota);
  // Sin nota se escribe directamente; con nota, primero se abre.
  const [abierta, setAbierta] = useState(!tieneNota);
  const [texto, setTexto] = useState("");
  const [ultima, setUltima] = useState("");
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState("");
  const [aviso, setAviso] = useState("");

  // Abrir una nota existente es una lectura del dato más sensible del sistema y queda en la
  // bitácora (RF18). Por eso es un botón explícito y no algo que ocurra al abrir la ventana.
  async function abrir() {
    setOcupado(true);
    setError("");
    try {
      const nota = await obtenerNota(citaId);
      setTexto(nota.contenido);
      setUltima(nota.actualizada_en);
      setAbierta(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error inesperado");
    } finally {
      setOcupado(false);
    }
  }

  async function guardar(e: { preventDefault: () => void }) {
    e.preventDefault();
    setOcupado(true);
    setError("");
    setAviso("");
    try {
      const nota = await guardarNota(citaId, texto);
      setExiste(true);
      setUltima(nota.actualizada_en);
      setAviso("Nota guardada.");
      onGuardada(); // la agenda debe saber que ya hay nota; si no, otro intento mostraría un editor vacío
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error inesperado");
    } finally {
      setOcupado(false);
    }
  }

  return (
    <section className="acciones nota" aria-labelledby="nota-titulo">
      <h3 id="nota-titulo">Nota clínica</h3>

      {!abierta ? (
        <>
          <div className="fila">
            <button type="button" className="btn" disabled={ocupado} onClick={abrir}>
              {ocupado ? "Abriendo…" : "Abrir nota clínica"}
            </button>
          </div>
          <p className="ayuda">Abrir la nota queda registrado en la bitácora de auditoría (RF18).</p>
        </>
      ) : (
        <form className="acciones" onSubmit={guardar}>
          <label className="field">
            <span>{existe ? "Contenido de la nota" : "Escribe la nota de esta cita"}</span>
            <textarea rows={6} maxLength={MAX} value={texto} onChange={(e) => setTexto(e.target.value)} />
          </label>
          <p className="ayuda">
            {texto.length} de {MAX} caracteres
            {ultima && ` · Última edición: ${fechaCompleta(fechaLocal(new Date(ultima)))}, ${hora(ultima)}`}
          </p>
          <div className="fila">
            <button type="submit" className="btn" disabled={ocupado || texto.trim() === ""}>
              {ocupado ? "Guardando…" : existe ? "Guardar cambios" : "Guardar nota"}
            </button>
          </div>
        </form>
      )}

      {aviso && (
        <p className="aviso aviso-ok" role="status">
          {aviso}
        </p>
      )}
      {error && (
        <p className="aviso aviso-error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
