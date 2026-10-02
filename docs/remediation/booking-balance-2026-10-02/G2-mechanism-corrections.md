# Corrección de mecanismo posterior al congelado G2

`tests/staff_notifications/test_f2_reopen.py`: la prueba inyectaba `NOW` al
worker, pero la reapertura usaba el reloj real del sistema. Al ejecutar después
de las 15:00 UTC, `next_attempt_at` quedaba en el futuro respecto al reloj del
worker. Se fija únicamente `app.notifications.service.datetime.now` a `NOW`.
Las aserciones de errores borrados, envío TEXT único, ausencia de plantilla y
estado SENT permanecen iguales. No se cambia el comportamiento de producción.

La alternativa descartada fue modificar la fecha de reintento de producción
para satisfacer un reloj incoherente del test. La corrección se registra en
un commit propio `test: fix mechanism freeze F2 reopen clock` y se declara como
la única diferencia de bytes respecto al manifiesto G2 original. El manifiesto
original conserva los bytes del commit rojo como evidencia.

Comprobación de la prueba corregida: 1 passed, 4.51 s. La corrección no modifica
el rojo inicial: allí fallaba la primera aserción, al conservar el código 131047.
