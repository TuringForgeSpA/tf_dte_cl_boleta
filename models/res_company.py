# -*- coding: utf-8 -*-
"""Configuración de boletas de la compañía.

Ruta real: models/res_company.py
"""
from __future__ import annotations

from odoo import fields, models
from odoo.tools import float_round

PARTNER_XMLID = 'tf_dte_cl_boleta.partner_tf_dte_cl_boleta_anonymous'
IVA_CODE = '14'


class ResCompany(models.Model):
    _inherit = 'res.company'

    tf_dte_cl_boleta_partner_id = fields.Many2one(
        'res.partner', string='Cliente de boletas',
        help='Cliente que se propone en las boletas nuevas. Mientras no tenga un RUT válido, '
             'la boleta se emite al RUT genérico 66666666-6 (consumidor final).',
    )
    tf_dte_cl_boleta_tax_id = fields.Many2one(
        'account.tax', string='IVA incluido para boletas', check_company=True,
        domain="[('type_tax_use', '=', 'sale'), ('tf_dte_cl_sii_code', '=', '14'), "
               "('price_include_override', '=', 'tax_included')]",
        help='En los diarios de boletas (39) reemplaza al IVA 19 % de los productos: '
             'el precio de la línea se interpreta con IVA incluido.',
    )
    tf_dte_cl_boleta_verify_url = fields.Char(
        string='Sitio de consulta de boletas',
        help='Dirección pública donde el consumidor verifica su boleta, impresa junto al timbre. '
             'Vacío: la dirección de este Odoo seguida de /boleta. El SII exige que esté en línea '
             'antes de aprobar la certificación.',
    )
    tf_dte_cl_boleta_public_xml = fields.Boolean(
        string='Entregar también el XML en la consulta pública',
        help='Por defecto la página de consulta entrega solo el PDF de la boleta.',
    )
    tf_dte_cl_boleta_pricelist_id = fields.Many2one(
        'product.pricelist', string='Precios al público (IVA incluido)', check_company=True,
        help='Precio con IVA incluido de cada producto en las boletas. Un producto sin regla en '
             'esta lista usa su precio de venta más los impuestos del producto, redondeado al peso.',
    )

    # ------------------------------------------------------------------
    # Preparación
    # ------------------------------------------------------------------
    def _tf_dte_cl_boleta_included_tax(self):
        """IVA 19 % incluido en el precio de la compañía; lo crea desde el IVA de ventas si falta."""
        self.ensure_one()
        Tax = self.env['account.tax'].with_context(active_test=False)
        domain = [
            *Tax._check_company_domain(self),
            ('type_tax_use', '=', 'sale'),
            ('tf_dte_cl_sii_code', '=', IVA_CODE),
            ('amount_type', '=', 'percent'),
            ('amount', '=', 19.0),
        ]
        included = Tax.search(domain + [('price_include_override', '=', 'tax_included')], limit=1)
        if included:
            return included
        base = Tax.search(domain + [('price_include_override', '!=', 'tax_included'), ('active', '=', True)],
                          order='sequence, id', limit=1)
        if not base:
            return Tax
        return base.copy({
            'name': '%s (incluido en el precio)' % base.name,
            'price_include_override': 'tax_included',
            'include_base_amount': False,
        })

    def _tf_dte_cl_boleta_setup(self) -> None:
        """Completa lo que falta para emitir boletas. No modifica lo ya configurado."""
        partner = self.env.ref(PARTNER_XMLID, raise_if_not_found=False)
        for company in self:
            if company.currency_id.name != 'CLP':
                continue  # las boletas se emiten en pesos
            vals = {}
            if not company.tf_dte_cl_boleta_partner_id and partner:
                vals['tf_dte_cl_boleta_partner_id'] = partner.id
            if not company.tf_dte_cl_boleta_tax_id:
                tax = company._tf_dte_cl_boleta_included_tax()
                if tax:
                    vals['tf_dte_cl_boleta_tax_id'] = tax.id
            if not company.tf_dte_cl_boleta_pricelist_id:
                vals['tf_dte_cl_boleta_pricelist_id'] = self.env['product.pricelist'].create({
                    'name': 'Precios al público (IVA incluido)',
                    'currency_id': company.currency_id.id,
                    'company_id': company.id,
                }).id
            if vals:
                company.write(vals)

    def _tf_dte_cl_boleta_verify_url(self) -> str:
        """Sitio de consulta impreso en las boletas, sin el protocolo."""
        self.ensure_one()
        url = self.tf_dte_cl_boleta_verify_url
        if not url:
            base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
            url = base.rstrip('/') + '/boleta'
        return url.split('://', 1)[-1].rstrip('/')

    # ------------------------------------------------------------------
    # Precio al público
    # ------------------------------------------------------------------
    def _tf_dte_cl_boleta_public_price(self, product, quantity, uom, date, with_taxes=True) -> float:
        """Precio unitario al público de un producto en una boleta.

        Se usa la lista de precios solo si la regla aplicable es de **precio fijo**: una
        regla por fórmula o porcentaje parte del precio de venta, que es neto, y su
        resultado no incluye el IVA. Sin regla fija, el precio de venta más los
        impuestos del producto (``with_taxes``), redondeado al peso.
        """
        self.ensure_one()
        pricelist = self.tf_dte_cl_boleta_pricelist_id
        if pricelist:
            price, rule_id = pricelist._compute_price_rule(
                product, quantity or 1.0, uom=uom, date=date,
            )[product.id]
            rule = self.env['product.pricelist.item'].browse(rule_id)
            if rule and rule.compute_price == 'fixed':
                return price
        taxes = product.taxes_id.filtered_domain(self.env['account.tax']._check_company_domain(self))
        if not with_taxes:
            taxes = taxes.browse()
        price = product.lst_price
        if uom and uom != product.uom_id:
            price = product.uom_id._compute_price(price, uom)
        if taxes:
            price = taxes.compute_all(price, currency=self.currency_id, quantity=1.0, product=product)['total_included']
        return float_round(price, precision_digits=self.currency_id.decimal_places)

    # ------------------------------------------------------------------
    # Unidad de Fomento (Ley 21.713)
    # ------------------------------------------------------------------
    def _tf_dte_cl_uf_value(self, date) -> float | None:
        """Pesos por UF a la fecha, desde la moneda CLF de Odoo; ``None`` si no hay tasa registrada."""
        self.ensure_one()
        clf = self.env.ref('base.CLF', raise_if_not_found=False)
        if not clf:
            return None
        has_rate = self.env['res.currency.rate'].sudo().search_count([
            ('currency_id', '=', clf.id),
            ('company_id', 'in', [self.root_id.id, False]),
            ('name', '<=', date),
        ], limit=1)
        if not has_rate:
            return None
        return self.env['res.currency']._get_conversion_rate(clf, self.currency_id, self, date)
