# -*- coding: utf-8 -*-
"""Reglas de montos de boletas (funciones puras).

Ruta real: tests/test_boleta_lines.py
"""
from odoo.tests import TransactionCase, tagged

from odoo.addons.tf_dte_cl.models.dte_lines import LineInfo, TaxInfo
from odoo.addons.tf_dte_cl_boleta.models.boleta_lines import (
    UF_FLOOR,
    UF_LIMIT,
    exceeds_uf_limit,
    gross_line_errors,
    gross_totals,
)

IVA_INCL = TaxInfo(name='IVA incluido', code='14', rate=19.0, price_include=True)
IVA_EXCL = TaxInfo(name='IVA', code='14', rate=19.0)
ILA = TaxInfo(name='ILA', code='27', rate=10.0)


def line(amount, taxes=(IVA_INCL,), label='L'):
    return LineInfo(label=label, product_name=label, quantity=1, price_unit=amount, subtotal=amount,
                    taxes=list(taxes))


@tagged('post_install', '-at_install')
class TestBoletaLines(TransactionCase):

    def test_gross_totals(self):
        totals = gross_totals([line(1000), line(1001), line(500, taxes=())])
        # Neto = round(2001 / 1,19) = 1682; IVA = 2001 - 1682; el total es la suma exacta de las líneas.
        self.assertEqual((totals['net'], totals['iva'], totals['exempt'], totals['total']), (1682, 319, 500, 2501))
        self.assertEqual(gross_totals([line(3000, taxes=())])['iva'], 0)

    def test_gross_rules(self):
        self.assertEqual(gross_line_errors('39', [line(1000)]), [])
        self.assertIn('incluido en el precio', ' '.join(gross_line_errors('39', [line(1000, taxes=(IVA_EXCL,))])))
        self.assertIn('impuestos adicionales', ' '.join(gross_line_errors('39', [line(1000, taxes=(IVA_INCL, ILA))])))
        self.assertIn('boleta exenta (41)', ' '.join(gross_line_errors('39', [line(1000, taxes=())])))
        self.assertIn('no lleva impuestos', ' '.join(gross_line_errors('41', [line(1000)])))
        self.assertEqual(gross_line_errors('41', [line(1000, taxes=())]), [])
        self.assertIn('descuentos o recargos globales', ' '.join(gross_line_errors('39', [line(1000)], True)))

    def test_uf_limit(self):
        floor = UF_LIMIT * UF_FLOOR
        self.assertIs(exceeds_uf_limit(floor, None), False)
        self.assertIsNone(exceeds_uf_limit(floor + 1, None))
        self.assertIs(exceeds_uf_limit(floor + 1, 39000), False)
        self.assertIs(exceeds_uf_limit(UF_LIMIT * 39000 + 1, 39000), True)
