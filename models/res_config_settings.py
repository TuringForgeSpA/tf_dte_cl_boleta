# -*- coding: utf-8 -*-
"""Ajustes de boletas (Contabilidad > Ajustes > Facturación electrónica Chile).

Ruta real: models/res_config_settings.py
"""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    tf_dte_cl_boleta_partner_id = fields.Many2one(
        related='company_id.tf_dte_cl_boleta_partner_id', readonly=False,
    )
    tf_dte_cl_boleta_tax_id = fields.Many2one(related='company_id.tf_dte_cl_boleta_tax_id', readonly=False)
    tf_dte_cl_boleta_verify_url = fields.Char(related='company_id.tf_dte_cl_boleta_verify_url', readonly=False)
    tf_dte_cl_boleta_public_xml = fields.Boolean(related='company_id.tf_dte_cl_boleta_public_xml', readonly=False)
    tf_dte_cl_boleta_pricelist_id = fields.Many2one(
        related='company_id.tf_dte_cl_boleta_pricelist_id', readonly=False,
    )

    def action_tf_dte_cl_boleta_setup(self):
        """Crea lo que falta para emitir boletas (cliente, IVA incluido y lista de precios)."""
        self.ensure_one()
        self.company_id._tf_dte_cl_boleta_setup()
        return {'type': 'ir.actions.client', 'tag': 'reload'}
