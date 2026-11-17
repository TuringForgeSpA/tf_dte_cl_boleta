# -*- coding: utf-8 -*-
"""Precio al público e IVA incluido en las líneas de boletas.

Ruta real: models/account_move_line.py

Los productos guardan su precio de venta neto y el IVA 19 % sin incluir
(facturas B2B). En un diario de boletas (39) la línea toma el precio con IVA
incluido (lista de precios al público o precio neto más impuestos, redondeado
al peso) y el IVA incluido de la compañía. En boletas exentas (41) los
impuestos no se cambian: un producto con IVA queda bloqueado al emitir.
"""
from odoo import api, fields, models

from .boleta_lines import AFFECTED_BOLETA, BOLETA_TYPES

IVA_CODE = '14'


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    def _tf_dte_cl_boleta_journal_type(self):
        self.ensure_one()
        move = self.move_id
        if (self.display_type != 'product' or not self.product_id or self.is_imported
                or move.move_type != 'out_invoice'):
            return False
        doc_type = move.journal_id.tf_dte_cl_document_type
        return doc_type if doc_type in BOLETA_TYPES else False

    @api.depends('product_id', 'product_uom_id')
    def _compute_tax_ids(self):
        super()._compute_tax_ids()
        for line in self:
            if line._tf_dte_cl_boleta_journal_type() != AFFECTED_BOLETA:
                continue
            included = line.move_id.company_id.tf_dte_cl_boleta_tax_id
            excluded = line.tax_ids.filtered(lambda tax: tax.tf_dte_cl_sii_code == IVA_CODE and not tax.price_include)
            if included and excluded:
                line.tax_ids = (line.tax_ids - excluded) | included

    @api.depends('product_id', 'product_uom_id')
    def _compute_price_unit(self):
        super()._compute_price_unit()
        for line in self:
            if not line._tf_dte_cl_boleta_journal_type():
                continue
            move = line.move_id
            line.price_unit = move.company_id._tf_dte_cl_boleta_public_price(
                line.product_id, line.quantity, line.product_uom_id,
                move.invoice_date or fields.Date.context_today(line),
                # Boleta exenta (41): sin IVA en el precio.
                with_taxes=line._tf_dte_cl_boleta_journal_type() == AFFECTED_BOLETA,
            )

