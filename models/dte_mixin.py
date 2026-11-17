# -*- coding: utf-8 -*-
"""Tipos de boleta en el ciclo de vida DTE e indicador de impresión del receptor.

Ruta real: models/dte_mixin.py
"""
from odoo import fields, models
from odoo.exceptions import UserError

BOLETA_SELECTION = [
    ('39', 'Boleta electrónica (39)'),
    ('41', 'Boleta no afecta o exenta electrónica (41)'),
]


def _block_uninstall(records):
    """Al desinstalar: no deja documentos tributarios emitidos sin tipo."""
    if records:
        raise UserError(records.env._(
            'No se puede desinstalar el módulo de boletas: hay %(count)s registros de %(model)s con tipo 39 o 41.',
            count=len(records), model=records._description,
        ))


BOLETA_ONDELETE = {'39': _block_uninstall, '41': _block_uninstall}


class TfDteClDocumentMixin(models.AbstractModel):
    _inherit = 'tf_dte_cl.document.mixin'

    tf_dte_cl_document_type = fields.Selection(selection_add=BOLETA_SELECTION, ondelete=BOLETA_ONDELETE)

    def _tf_dte_cl_print_receiver(self) -> bool:
        """Si la representación impresa muestra el bloque del receptor."""
        return True

    def _tf_dte_cl_verify_url(self) -> str:
        """Sitio donde se verifica el documento, impreso junto al timbre."""
        return 'www.sii.cl'
