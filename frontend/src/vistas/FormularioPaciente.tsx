import { useEffect, useRef, useState } from "react";
import { actualizarPaciente, crearPaciente, type DatosPaciente } from "../api";
import type { Paciente } from "../api/dominio";
import { hoy } from "../fechas";
import "./formulario.css";

type Props = Readonly<{
  /** Paciente a editar; sin él, el formulario registra uno nuevo. */
  paciente?: Paciente;
  onCerrar: () => void;
  onGuardado: (p: Paciente) => void;
}>;

const VACIO: DatosPaciente = { identificacion: "", nombre: "", fecha_nacimiento: "", telefono: "", correo: "" };

export default function FormularioPaciente({ paciente, onCerrar, onGuardado }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [datos, setDatos] = useState<DatosPaciente>(paciente ?? VACIO);
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState("");

  // <dialog> nativo, igual que el detalle de la cita: foco atrapado y cierre con Escape.
  useEffect(() => {
    if (!ref.current?.open) ref.current?.showModal();
  }, []);

  const campo = (clave: keyof DatosPaciente) => ({
    value: datos[clave],
    onChange: (e: { target: { value: string } }) => setDatos({ ...datos, [clave]: e.target.value }),
  });

  async function guardar(e: { preventDefault: () => void }) {
    e.preventDefault();
    setEnviando(true);
    setError("");
    try {
      const guardado = paciente ? await actualizarPaciente(paciente.id, datos) : await crearPaciente(datos);
      onGuardado(guardado);
      ref.current?.close();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error inesperado");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <dialog ref={ref} className="detalle formulario" aria-labelledby="form-titulo" onClose={onCerrar}>
      <form className="detalle-cuerpo" onSubmit={guardar}>
        <header className="detalle-head">
          <h2 id="form-titulo">{paciente ? "Editar paciente" : "Nuevo paciente"}</h2>
          <button type="button" className="btn btn-icon" aria-label="Cerrar" onClick={() => ref.current?.close()}>
            ×
          </button>
        </header>

        <div className="campos">
          <label className="field campo-ancho">
            <span>Nombre completo</span>
            <input required autoComplete="off" {...campo("nombre")} />
          </label>
          <label className="field">
            <span>Identificación</span>
            <input required autoComplete="off" placeholder="1-0234-0567" {...campo("identificacion")} />
          </label>
          <label className="field">
            <span>Fecha de nacimiento</span>
            <input required type="date" min="1900-01-01" max={hoy()} {...campo("fecha_nacimiento")} />
          </label>
          <label className="field">
            <span>Teléfono</span>
            <input type="tel" autoComplete="off" placeholder="8123-4567" {...campo("telefono")} />
          </label>
          <label className="field">
            <span>Correo</span>
            <input type="email" autoComplete="off" placeholder="nombre@correo.cr" {...campo("correo")} />
          </label>
        </div>

        <p className="ayuda">Guardar los datos de contacto queda registrado en la bitácora de auditoría (RF18).</p>

        {error && (
          <p className="aviso aviso-error" role="alert">
            {error}
          </p>
        )}

        <div className="fila">
          <button type="button" className="btn" onClick={() => ref.current?.close()}>
            Cancelar
          </button>
          <button type="submit" className="btn btn-cta" disabled={enviando}>
            {enviando ? "Guardando…" : paciente ? "Guardar cambios" : "Registrar paciente"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
