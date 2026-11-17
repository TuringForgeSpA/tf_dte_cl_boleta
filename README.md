# tf_dte_cl_boleta

Boletas electrónicas para Odoo 18 sobre `tf_dte_cl`: boleta electrónica (39),
boleta no afecta o exenta electrónica (41) y notas de crédito (61) sobre
boletas, emitidas desde Contabilidad. Versión 18.0.1.1.0.

**Estado:** set de pruebas de boletas **aprobado** en el ambiente de
certificación del SII (noviembre de 2026) con esta versión del módulo.

El Punto de Venta irá en un módulo aparte (`tf_dte_cl_boleta_pos`), para que
una empresa que solo emite boletas desde Contabilidad no tenga que instalarlo.

## Fuentes

- SII, *Formato boletas electrónicas de ventas y servicios*, v4.2 (2025-09-08).
- SII, `EnvioBOLETA_v11.xsd` (idéntico al que trae la librería).
- SII, *Instructivo técnico de boleta electrónica* (2021-10-28): API REST propia
  (semilla, token, envío y consultas) y hasta 500 boletas por envío.
- Res. Ex. SII N° 53 de 2022: desde el 1 de agosto de 2022 no se envía el
  Resumen de Ventas Diarias (ex RCOF). El Registro de Ventas se arma con las
  boletas recibidas por el SII.

## Qué hace

| Tema | Comportamiento |
|---|---|
| Diarios | Tipo DTE 39 o 41 en diarios de venta |
| Precio | En diarios 39 y 41 la línea toma el **precio al público**: la regla de **precio fijo** de la lista de precios configurada o, si no hay, el precio de venta más los impuestos del producto (solo en 39), redondeado al peso. Las reglas por fórmula o porcentaje se ignoran porque parten del precio neto. El precio se propone al elegir el producto: si se cambia el diario de un borrador, hay que volver a elegirlo |
| IVA | En diarios 39, el IVA 19 % del producto se reemplaza por el **IVA incluido** de la compañía. Las boletas 41 no llevan impuestos |
| Receptor | Por defecto, «Consumidor final» (66666666-6). Con un cliente con RUT válido, la boleta va a su RUT y nombre |
| XML | Detalle bruto (`PrcItem`, `MontoItem` con IVA), `IndServicio` 3; `MntNeto` = total afecto / 1,19 redondeado e `IVA` por diferencia, para que el total sea exactamente la suma de las líneas |
| Envío | Sobre `EnvioBOLETA`, por la API REST del SII (`api=True` en el núcleo). Mismo ciclo del núcleo: firma al publicar, envío idempotente, consulta y estados |
| Nota de crédito | Desde una boleta aceptada: diario 61, referencia a la boleta (`TpoDocRef` 39/41), montos brutos (`MntBruto` 1), receptor como en la boleta. Va en un `EnvioDTE` normal |
| Impresión | Formatos A4 y térmico del núcleo: sin bloque de receptor si es anónimo (queda la fecha), totales con neto, exento, «IVA 19 % incluido» y total. Sin copia cedible |
| Correo | El envío estándar de Odoo (botón **Enviar**) manda el PDF al correo del cliente |

### Configuración que se crea al instalar

Para cada compañía con un IVA 19 % de ventas con código SII 14:

- cliente de boletas: «Consumidor final»;
- impuesto «… (incluido en el precio)», copia del IVA de ventas con precio incluido;
- lista de precios «Precios al público (IVA incluido)», vacía.

Se revisa y completa en *Contabilidad > Ajustes > Facturación electrónica Chile >
Boletas* (botón **Crear lo que falta para boletas**).

## Consulta pública de boletas

El SII exige que el sitio de consulta esté impreso en la boleta y en línea antes
de aprobar la certificación. El módulo publica `/boleta` en el mismo Odoo:

- página pública, sin inicio de sesión, que pide RUT del emisor, tipo, folio,
  fecha de emisión y monto total;
- con coincidencia exacta de los cinco datos entrega **solo el PDF** de esa
  boleta aceptada (y su XML si se habilita en Ajustes); si no, responde siempre
  «no encontrada»;
- hasta 10 consultas por IP cada 10 minutos;
- no lista ni busca por aproximación, y lee con sudo solo el registro encontrado.

La dirección impresa junto al timbre es **Sitio de consulta de boletas**
(Ajustes > Facturación electrónica Chile > Boletas); vacía, la de este Odoo con
`/boleta`. Detrás de un proxy, Odoo debe correr con `proxy_mode = True` para
limitar por la IP real del cliente.

## Set de pruebas de certificación

Procedimiento con el que se aprobó el set. Según el correo del SII («Proceso Certificación de Boletas Electrónicas»):
CAF de 5 folios, set en **un solo sobre** y **RCOF** asociado, ambos por
**upload** en certificación, y pedir la revisión con el Track ID. **Plazo: 24
horas desde que se descarga el CAF.**

1. En la boleta, campo **Caso del set de pruebas** (solo en certificación):
   `CASO-1` a `CASO-5`. Se informa como `CodRef` SET y `RazonRef` CASO-n.
2. Las boletas con caso **no se envían solas** (ni el cron ni el botón).
3. Seleccionarlas en la lista y usar *Acción > Set de certificación de boletas*:
   arma y firma un único EnvioBOLETA y el RCOF (ConsumoFolio_v10).
4. Subir **los dos** archivos en el sitio de certificación del SII: el sobre de
   boletas y el RCOF. Si falta el RCOF, el SII rechaza el set.
5. Pedir la revisión con el **Track ID del sobre de boletas**, no con el del
   RCOF.

Lo aprendido al aprobarlo:

- Si se rehace el set el mismo día, el RCOF nuevo debe llevar un **SecEnvio
  mayor** que el anterior (campo del asistente); con el mismo número, el SII lo
  objeta.
- Revisar las cantidades y montos de cada caso contra el set antes de armar el
  sobre: un error de digitación se rechaza como «líneas no cuadran».
- El RCOF solo se exige en certificación: en producción no se envía (Res. Ex.
  N° 53 de 2022).

La unidad «kg» de Odoo se informa como `Kg`, como pide el caso 5.

## Validaciones

- Boleta 39 con al menos una línea con IVA; boleta 41 sin impuestos.
- IVA incluido en el precio en todas las líneas afectas.
- Sin impuestos adicionales (ILA) ni descuentos o recargos globales.
- Cada línea debe sumar pesos enteros con IVA (un descuento en % o una cantidad
  decimal pueden dejar centavos; Odoo y el DTE redondearían distinto).
- Un cliente con RUT inválido bloquea la emisión; sin RUT, la boleta va al
  consumidor final.
- Una nota de crédito sobre boleta no puede mezclar líneas afectas y exentas
  (la librería solo informa `MntBruto` sin montos exentos).
- Sin referencias en la boleta, salvo el caso del set de certificación (sí en
  sus notas de crédito).
- **Ley 21.713**: sobre 135 UF la boleta exige medio de pago (`MedioPago`), que
  la librería no transmite; esas boletas se bloquean y se pide emitir factura.
  Para verificarlo se usa la UF de la moneda **CLF** de Odoo. Bajo 4.050.000
  pesos (135 UF a 30.000 pesos) no se consulta la UF.

## Cambios en otros módulos

- `tf_dte_cl` 18.0.2.8.0: puntos de extensión para tipos adicionales, API REST,
  receptor e IVA incluido (ver su README).
- `tf_dte_cl_intercambio` 18.0.6.1.0: las boletas y sus notas de crédito quedan
  fuera del intercambio entre contribuyentes.
- `tf_l10n_cl_f29` 18.0.1.1.0: suma las boletas (39 en 110/111, 41 en 586/142,
  sus notas de crédito en 509/510). No depende de este módulo.

## Límites de facturacion_electronica 0.24.0 en boletas

| Campo del formato | Situación | Efecto |
|---|---|---|
| `MedioPago` (obligatorio sobre 135 UF) | No se transmite | Boletas sobre 135 UF bloqueadas |
| `RUTProvSW` (condicional: RUT del proveedor de software o del emisor si es desarrollo propio) | Comentado en la librería | No se informa; el SII aprobó el set sin él |
| `MntNeto` en boleta 41 | La librería informa `<MntNeto>0</MntNeto>` (el formato lo marca como no aplicable) | Válido contra el XSD; sin observaciones del SII hasta ahora |
| `CorreoRecep`, `TelefonoRecep` | No se transmiten en boletas | Sin efecto: son opcionales |
| Referencias en boletas | La librería omite `TpoDocRef` y `FolioRef` | Las boletas solo llevan la referencia del set (`CodRef` SET, `RazonRef` CASO-n), aceptada por el SII |

Las respuestas JSON de la API REST se interpretan con los campos que lee la
librería (`trackid`, `estado`, `estadistica`, `detalle_rep_rech`, `codigo`,
`descripcion`).

## Validado en certificación

- XML de la boleta y del sobre `EnvioBOLETA`, timbre y firma.
- Detalle bruto con `IndServicio` 3, `MntNeto` por división y `IVA` por
  diferencia: el SII no objetó los totales del set.
- Referencia del set (`CodRef` SET, `RazonRef` CASO-n) y unidad `Kg`.
- RCOF (ConsumoFolio_v10) con `SecEnvio` creciente.
- Sitio de consulta impreso en el timbre.

## Por confirmar con los primeros envíos en producción

El set se entregó por **upload**, así que la **API REST** del SII no se ejercitó
en la certificación:

- Respuestas JSON reales de la API: códigos de estado del envío y del documento.
  Un envío cuya consulta no da un código concluyente queda en *Envío sin
  confirmar* hasta revisarlo.
- Notas de crédito sobre boletas en un envío real (van en `EnvioDTE` normal).

Conviene revisar a mano el estado de las primeras boletas y notas de crédito.

## Pendiente

- Antes de emitir en producción: **Declaración de Cumplimiento** y autorización
  del SII para boletas; luego diarios 39/41 y CAF de producción.
- Punto de Venta (`tf_dte_cl_boleta_pos`).
- Envío agrupado (hasta 500 boletas por sobre): hoy se envía una boleta por sobre.

## Pruebas

```bash
./odoo-bin -c /etc/odoo.conf -d odoo_tests --without-demo=all \
    -i tf_dte_cl_boleta --test-enable --test-tags /tf_dte_cl,/tf_dte_cl_boleta \
    --http-port=8070 --logfile=/tmp/odoo_tests.log --stop-after-init
```

Incluye una prueba que firma una boleta y una nota de crédito con la librería
real (sin red): la librería valida el DTE y el sobre contra los XSD del SII.

© 2026 Turing Forge SpA. Distribuido bajo LGPL-3.
