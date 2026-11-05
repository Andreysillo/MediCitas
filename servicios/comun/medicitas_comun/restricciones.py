"""Qué decirle al usuario cuando el motor rechaza algo, según la restricción que saltó.

Las restricciones están en db/migrations/. Aquí solo se les pone una frase clara; si una no aparece, la
respuesta usa el mensaje genérico de su tipo. Al agregar una restricción importante, agregar aquí su mensaje.
"""

MENSAJES = {
    "horario_sin_solape": "Ese bloque se solapa con otro del mismo día",
    "cita_sin_solape_profesional": "El profesional ya tiene una cita en ese horario",
    "cita_sin_solape_paciente": "El paciente ya tiene una cita en ese horario",
}
