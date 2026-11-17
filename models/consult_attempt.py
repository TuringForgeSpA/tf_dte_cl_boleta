# -*- coding: utf-8 -*-
"""Intentos de la consulta pública de boletas, para limitarlos por IP.

Ruta real: models/consult_attempt.py

Solo lo escribe el controlador con sudo; ningún grupo de usuarios tiene
acceso de lectura salvo administradores del sistema.
"""
from __future__ import annotations

from datetime import timedelta

from odoo import api, fields, models

# Criterio tf_dte_cl: hasta 10 consultas por IP cada 10 minutos.
MAX_ATTEMPTS = 10
WINDOW_MINUTES = 10
KEEP_DAYS = 1


class TfDteClBoletaConsultAttempt(models.Model):
    _name = 'tf_dte_cl_boleta.consult.attempt'
    _description = 'Intento de consulta pública de boleta'
    _order = 'id desc'
    _log_access = False

    ip = fields.Char(required=True, index=True)
    attempt_date = fields.Datetime(required=True, index=True, default=fields.Datetime.now)

    @api.model
    def _tf_dte_cl_register(self, ip: str) -> bool:
        """Registra un intento. ``False`` si la IP superó el límite."""
        now = fields.Datetime.now()
        self.search([('attempt_date', '<', now - timedelta(days=KEEP_DAYS))]).unlink()
        recent = self.search_count([
            ('ip', '=', ip),
            ('attempt_date', '>=', now - timedelta(minutes=WINDOW_MINUTES)),
        ])
        if recent >= MAX_ATTEMPTS:
            return False
        self.create({'ip': ip, 'attempt_date': now})
        return True
