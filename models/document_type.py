# -*- coding: utf-8 -*-
"""Tipos de documento de referencia de boletas.

Ruta real: models/document_type.py
"""
from odoo import api, models

from .boleta_lines import BOLETA_TYPES


class TfDteClDocumentType(models.Model):
    _inherit = 'tf_dte_cl.document_type'

    @api.model
    def _tf_dte_cl_boleta_activate_types(self):
        """Activa las boletas 39 y 41 (el núcleo las trae archivadas)."""
        self.with_context(active_test=False).search([('code', 'in', list(BOLETA_TYPES))]).write({'active': True})
