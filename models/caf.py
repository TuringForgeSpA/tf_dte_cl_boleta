# -*- coding: utf-8 -*-
"""CAF y sobres de boletas.

Ruta real: models/caf.py

El ambiente del CAF (IDK), la toma de folios con bloqueo y los folios por
anular son los del núcleo; aquí solo se habilitan los tipos 39 y 41.
"""
from odoo import fields, models

from .dte_mixin import BOLETA_ONDELETE, BOLETA_SELECTION


class TfDteClCaf(models.Model):
    _inherit = 'tf_dte_cl.caf'

    document_type = fields.Selection(selection_add=BOLETA_SELECTION, ondelete=BOLETA_ONDELETE)


class TfDteClEnvelope(models.Model):
    _inherit = 'tf_dte_cl.envelope'

    document_type = fields.Selection(selection_add=BOLETA_SELECTION, ondelete=BOLETA_ONDELETE)
