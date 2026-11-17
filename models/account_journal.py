# -*- coding: utf-8 -*-
"""Diarios de venta de boletas (39 y 41).

Ruta real: models/account_journal.py
"""
from odoo import fields, models

from .dte_mixin import BOLETA_SELECTION


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    tf_dte_cl_document_type = fields.Selection(selection_add=BOLETA_SELECTION,
                                              ondelete={'39': 'set null', '41': 'set null'})
