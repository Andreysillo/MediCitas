"""Forma de lo que entra y sale de la API de horarios y bloqueos (RF5, RF6). FastAPI los usa para validar y para /docs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

# "08:00", no "8:00" ni "08:00:30": con ceros a la izquierda, comparar el texto es comparar la hora.
Hora = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$", examples=["08:00"])]


class ProfesionalGestionable(BaseModel):
    id: UUID
    nombre: str
    especialidad: str


class NuevoHorario(BaseModel):
    dia_semana: int = Field(ge=1, le=7, description="ISO: 1 lunes ... 7 domingo")
    hora_inicio: Hora
    hora_fin: Hora

    @model_validator(mode="after")
    def fin_despues_del_inicio(self):
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("La hora de fin debe ser posterior a la de inicio")
        return self


class Horario(NuevoHorario):
    id: UUID
    profesional_id: UUID


class NuevoBloqueo(BaseModel):
    # AwareDatetime exige zona horaria ("...-06:00" o "...Z"): un instante sin zona es ambiguo.
    inicio: AwareDatetime
    fin: AwareDatetime
    motivo: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]

    @model_validator(mode="after")
    def fin_despues_del_inicio(self):
        if self.fin <= self.inicio:
            raise ValueError("El fin del bloqueo debe ser posterior a su inicio")
        return self


class CitaEnConflicto(BaseModel):
    """Una cita reservada que un bloqueo o un cambio de horario dejó sin cubrir. Recepción decide qué hacer."""

    id: UUID
    profesional_id: UUID
    paciente_id: UUID
    servicio_id: UUID
    inicio: datetime
    fin: datetime
    estado: str
    paciente: str
    servicio: str


class Bloqueo(BaseModel):
    id: UUID
    profesional_id: UUID
    inicio: datetime
    fin: datetime
    motivo: str
    conflictos: list[CitaEnConflicto]


class HorarioEliminado(BaseModel):
    conflictos: list[CitaEnConflicto]
