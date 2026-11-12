# Modelos de pronóstico: explicación

Versión explicativa de los experimentos de la v0.1. El detalle técnico completo está en [`ml/notebooks/README.md`](../ml/notebooks/README.md).

## 1. El problema

Para cada producto, a partir de las ventas (salidas) de los días anteriores, calcular **7 números**: las unidades que se venderán cada uno de los próximos 7 días. Su suma es el consumo de la semana.

## 2. Los datos

### 2.1 Qué datos usamos

Conjunto público de Kaggle *Store Item Demand Forecasting Challenge*:

- 10 tiendas × 50 productos = **500 series** (una serie = las ventas diarias de un producto en una tienda).
- 5 años completos, del 2013-01-01 al 2017-12-31: 1,826 días por serie y 913,000 registros.
- Cada registro: `fecha, tienda, producto, ventas`.

### 2.2 Por qué este conjunto

- Tiene exactamente la forma del problema: unidades por producto y por día.
- Es externo y conocido. Si inventáramos los datos, el modelo aprendería las reglas con que los inventamos y el resultado no demostraría nada.
- Tiene 5 años, suficientes para observar la estacionalidad anual y evaluar sobre un año completo.

### 2.3 Cómo verificamos que los datos estuvieran bien

| Verificación | Resultado |
|---|---|
| Fechas faltantes | Ninguna: todas las series tienen los 1,826 días. Lo comprueba un `assert` en el notebook 02. |
| Valores vacíos | Ninguno (`assert`). |
| Rango de ventas | Entre 0 y 231 unidades/día; mediana de 47. No hay valores negativos ni absurdos. |
| Días sin venta | 0.0001%: la demanda no es intermitente, por eso no aplica Croston. |
| Patrones esperables | Se vende más el fin de semana y en verano (máximo en julio, mínimo en enero), lo que confirma que los datos tienen sentido. |
| Coherencia entre experimentos | El error del modelo naive en diciembre de 2017 da **8.74** en los dos notebooks, que procesan los datos de forma independiente. |
| Fuga de información | Un `assert` garantiza que ningún dato de entrenamiento pertenece al período de evaluación. |

**Limitación:** es un conjunto limpio, sin productos agotados, huecos ni productos nuevos. Los datos reales tendrán más ruido.

## 3. Unidad de medida y métricas

**Unidad de referencia:** unidades de producto por día. Todos los pronósticos y errores se expresan en esa unidad o en porcentaje sobre ella.

| Métrica | Qué mide | Ejemplo |
|---|---|---|
| **MAE** (error absoluto medio) | En cuántas unidades se equivoca, en promedio, el pronóstico de cada día. | MAE = 6.45 indica que cada día el pronóstico se aleja unas 6 unidades de lo real, sobre una venta media de ~59. |
| **WAPE** | El mismo error, en porcentaje del total vendido: suma de errores / suma de ventas. | WAPE = 11% indica que, de cada 100 unidades vendidas, el pronóstico se equivoca en 11. |
| **WAPE semanal** | El WAPE calculado sobre el **total de los 7 días**. Es la métrica principal, porque la compra se decide por semana. | 5.3%: en una semana de ~410 unidades, el error es de ~22. |
| **Sesgo** | Si el modelo tiende a pasarse (+) o a quedarse corto (−). | +5% implica comprar de más; −5%, quedarse sin stock. |

**¿Por qué WAPE y no MAPE?** El MAPE divide el error de cada día entre la venta de ese día; si un día se vendió 0, la división no está definida. El WAPE divide entre el total, que nunca es cero.

**¿Por qué dos métricas (diaria y semanal)?** Los errores diarios se compensan parcialmente en la semana: un día se pasa y otro se queda corto. Un modelo puede ser peor día a día y mejor en el total semanal; ocurrió en el experimento 1.

## 4. Cómo evaluamos: backtesting

La evaluación simula el uso real: **el modelo solo ve el pasado y predice el futuro**.

1. Se elige un día de corte (por ejemplo, domingo 3 de diciembre de 2017).
2. El modelo recibe los datos **hasta ese día**.
3. Pronostica los 7 días siguientes.
4. Se compara con lo que realmente se vendió.
5. Se repite con muchos cortes para que una semana rara no decida el resultado.

**¿Por qué no una partición aleatoria (80/20)?** Mezclaría días futuros con pasados: el modelo podría "ver" datos posteriores a la fecha que pronostica. Es como dar el examen con las respuestas, y el error saldría artificialmente bajo.

## 5. Los modelos

Probamos 6 modelos de 4 tipos:

| Modelo | Tipo | ¿Lo entrenamos nosotros? | Rol |
|---|---|---|---|
| Naive estacional | Regla | No (no tiene nada que aprender) | Línea base |
| Promedio de 4 semanas | Regla | No | Línea base |
| AutoETS | Algoritmo estadístico | Se ajusta solo a cada serie | Método clásico |
| Chronos-Bolt | IA preentrenada (transformer) | No: la entrenó Amazon | IA de referencia |
| **LightGBM** | Árboles de decisión (machine learning) | **Sí** | Modelo entrenado |
| **MLP** | Red neuronal (deep learning) | **Sí** | Candidato para el ESP32 |

Un **modelo de regla** es una fórmula fija escrita por una persona: no aprende nada de los datos ni tiene parámetros que ajustar. Los dos primeros modelos son de este tipo.

### 5.1 Naive estacional (regla)

- **"Naive"** significa "ingenuo": el modelo no aprende, solo copia.
- **"Estacional"** indica que copia respetando el ciclo que se repite (la "estación"), que en este caso es la semana de 7 días.
- **La regla:** cada día se pronostica con lo que se vendió **el mismo día de la semana anterior**. En fórmula: ŷ(t) = y(t − 7).

  ```
  Semana pasada (real):    lun 8 · mar 5 · mié 6 · jue 7 · vie 8 · sáb 10 · dom 7
  Pronóstico esta semana:  lun 8 · mar 5 · mié 6 · jue 7 · vie 8 · sáb 10 · dom 7   ← copia exacta
  ```

- **Por qué se usa:** es la **línea base**, el mínimo que cualquier modelo debe superar. Si un modelo complejo no le gana a "copiar la semana pasada", no aporta nada. Aun así, es difícil de superar: Chronos solo lo empató en el total semanal.

### 5.2 Promedio de 4 semanas (regla)

- **La regla:** cada día se pronostica con el promedio de ese mismo día en las últimas 4 semanas. Ejemplo: si los últimos 4 lunes se vendieron 8, 9, 7 y 8, el pronóstico para el lunes es 8.
- **Por qué se usa:** para comprobar si promediar reduce el efecto de una semana atípica. Resultó el peor, porque mira un mes hacia atrás y tarda en reaccionar a los cambios de temporada.

### 5.3 AutoETS (algoritmo estadístico)

- **Qué hace:** descompone la serie en **nivel** (cuánto se vende normalmente), **tendencia** (si sube o baja) y **estacionalidad** (patrón semanal), y proyecta cada parte hacia adelante. Es "suavizado exponencial": los días recientes pesan más que los antiguos.
- **"Auto":** prueba varias configuraciones por serie y elige la mejor según un criterio estadístico.
- **Por qué:** es el método estadístico estándar en pronóstico de demanda. Representa "lo clásico".
- **Desventaja:** lento; tardó 33 minutos para 500 series en 4 semanas.

### 5.4 Chronos-Bolt small (IA preentrenada)

- **Qué es:** un modelo de IA de Amazon (~48 millones de parámetros, arquitectura transformer, como los modelos de lenguaje), entrenado con miles de series de tiempo de todo tipo. Igual que un modelo de lenguaje predice la siguiente palabra, Chronos predice los siguientes valores de una serie.
- **Cómo lo usamos:** *zero-shot*, es decir, sin entrenarlo con nuestros datos. Se le pasa el historial y entrega el pronóstico.
- **Por qué:** comprobar si una IA general, sin entrenamiento, es suficiente. Además entrega un rango (P10–P90) y funciona con poco historial.
- **Desventaja:** 183 MB. No cabe en un ESP32.

### 5.5 LightGBM (árboles de decisión)

- **Qué es:** un **árbol de decisión** es una serie de preguntas sí/no. Por ejemplo: "¿la venta del último sábado fue mayor que el promedio?" → "¿mañana es domingo?" → pronóstico = 1.2 × promedio.
- **Boosting:** en lugar de un solo árbol, se construyen cientos en secuencia, y cada árbol nuevo corrige los errores de los anteriores. En total usamos 2,923 árboles.
- **Por qué:** es el método que suele ganar en competencias de pronóstico con datos en tabla (incluida la competencia M5 de Walmart). Es el modelo "fuerte" contra el cual medir la red.
- **Desventaja:** 8.9 MB. Demasiado grande para el ESP32.

### 5.6 MLP (red neuronal)

Es el modelo que construimos y entrenamos nosotros, y el que irá en el ESP32. MLP significa *Multi-Layer Perceptron* (perceptrón multicapa).

**Qué es una neurona.** Una función pequeña que:
1. recibe varios números;
2. multiplica cada uno por un **peso** (cuánto le importa esa entrada);
3. los suma y añade un valor fijo (*sesgo*);
4. aplica **ReLU**: si el resultado es negativo, lo convierte en 0; si es positivo, lo deja igual. Esto permite aprender relaciones que no son líneas rectas.

**Qué significa 42 → 64 → 32 → 7.** Son las capas de la red y cuántos números hay en cada una:

```
 42 entradas           64 neuronas            32 neuronas          7 salidas
 (lo que ve el   →     (capa oculta 1:   →    (capa oculta 2:  →   (lun, mar, mié,
  modelo, sec. 6.1)     combina las            combina los          jue, vie, sáb, dom)
                        entradas)              patrones)
```

- **42 entradas:** los 42 números de cada ejemplo (sección 6.1).
- **64 neuronas:** cada una mira las 42 entradas y detecta algún patrón (por ejemplo, "el fin de semana pasado se vendió mucho").
- **32 neuronas:** combinan esos patrones en otros más generales.
- **7 salidas:** un número por cada día pronosticado.

Las capas "ocultas" se llaman así porque sus valores no se ven desde fuera: son cálculos intermedios.

**Parámetros (5,063).** Son todos los pesos y sesgos que la red aprende:
(42×64 + 64) + (64×32 + 32) + (32×7 + 7) = 2,752 + 2,080 + 231 = **5,063**. Ocupan unos 20 KB (4 bytes cada uno) o unos 5 KB en int8 (1 byte cada uno). Caben en el ESP32-S3.

**Qué es entrenar la red.** Al inicio, los pesos son aleatorios y la red pronostica mal. En cada paso se le muestran 512 ejemplos, se mide cuánto se equivocó (MAE) y el optimizador **Adam** ajusta un poco cada peso en la dirección que reduce el error. Una **época** es una pasada completa por todos los ejemplos de entrenamiento.
- **Por qué una red densa y no una LSTM:** las capas densas tienen soporte completo en TensorFlow Lite Micro; las recurrentes (LSTM) tienen soporte limitado en microcontroladores. Como las entradas ya resumen el historial, una red densa basta.

## 6. Cómo entrenamos LightGBM y la red

### Idea clave: dos preguntas distintas

Es fácil confundir estas dos cosas:

| Pregunta | Respuesta | Sección |
|---|---|---|
| ¿Qué contiene **cada ejemplo**? | 42 números de entrada (las ventas de antes del corte) y 7 de respuesta (las ventas de después) | 6.1 |
| ¿**De qué años** salen los ejemplos? | Entrenamiento: 2014–2015 · Validación: 2016 · Prueba: 2017 | 6.2 |

**Un ejemplo** es una "foto" tomada en un día de corte: lo que se sabía hasta ese día (entrada) y lo que pasó los 7 días siguientes (respuesta). Ejemplo con corte el **domingo 7 de junio de 2015**, para un producto:

```
           ENTRADA (42 números)                                        RESPUESTA (7 números)
 ┌─────────────────────────────────────────────────┐                ┌─────────────────────┐
 │ ventas del 11 may al 7 jun de 2015 (28 días)    │                │ ventas reales del   │
 │ ventas del 9 al 15 jun de 2014 (misma semana,   │      →         │ 8 al 14 jun de 2015 │
 │   año anterior: 7 días)                         │   el modelo    │ (lo que debe        │
 │ "el primer día pronosticado es lunes" (7)       │   aprende a    │  acertar)           │
 └─────────────────────────────────────────────────┘   pasar de una └─────────────────────┘
                                                        a la otra
```

Se toma una foto así **por cada día de corte y cada producto**. Los cortes de 2014–2015 dan 697 días × 500 productos = 348,500 ejemplos de entrenamiento.

### 6.1 Qué ve el modelo (42 variables de entrada)

Para cada producto y cada día de corte se arma una fila con:

| Variables | Cantidad | Para qué |
|---|---|---|
| Ventas de los últimos 28 días | 28 | Nivel actual y patrón semanal reciente |
| Ventas de la misma semana del año anterior | 7 | Anticipar la temporada (por ejemplo, la caída de diciembre) |
| Día de la semana del primer día pronosticado | 7 | Saber en qué parte de la semana empieza el pronóstico |

La respuesta esperada son las ventas reales de los 7 días siguientes.

**Normalización:** todo se divide por el promedio de los últimos 28 días del producto. Así, un producto que vende 10 al día y otro que vende 100 se ven parecidos, y **un solo modelo** sirve para los 500. Al final, el pronóstico se multiplica por ese promedio y vuelve a estar en unidades.

**Variables excluidas a propósito:**
- **El nombre del producto:** el modelo memorizaría los productos de Kaggle y no serviría para nuestro inventario.
- **La fecha** (mes, día del año): memorizaría el calendario de este conjunto. La variable "misma semana del año anterior" obtiene la temporada del propio producto.

Con estas decisiones, el modelo es transferible a otro negocio.

### 6.2 División de los datos

| Conjunto | Período | Ejemplos | Para qué |
|---|---|---|---|
| Entrenamiento | 2014–2015 | 348,500 | El modelo aprende |
| Validación | 2016 | 180,000 | Decidir cuándo parar de entrenar |
| Prueba | 2017 (52 semanas) | 26,000 | Nota final, usada **una sola vez** |

2013 solo se usa como historial: la variable anual necesita un año previo.

Cada conjunto se usa de una forma distinta:

- **Entrenamiento (2014–2015):** los únicos ejemplos con los que el modelo **cambia sus pesos**.
- **Validación (2016):** el modelo **no aprende** de estos ejemplos. Tras cada época de entrenamiento se mide su error en 2016 para saber si sigue mejorando con datos que no ha visto. Cuando deja de mejorar, se detiene (sección 6.3).
- **Prueba (2017):** se usa una sola vez, al final, con el modelo ya terminado (sección 6.5).

### 6.3 Proceso de entrenamiento

1. **Parada temprana:** el modelo entrena con 2014–2015 y, en cada ronda, se mide su error en 2016. Cuando deja de mejorar, se detiene. Esto evita el **sobreajuste** (memorizar en lugar de aprender).
   - LightGBM: entre 310 y 521 árboles según el día pronosticado.
   - Red: la mejor época fue la 11, de un máximo de 100.
2. **Reentrenamiento final:** con el número de rondas ya elegido, se entrena de nuevo con 2014–2016.
3. **Prueba:** se pronostican las 52 semanas de 2017, que el modelo nunca vio.

**Detalles de LightGBM:** 7 modelos, uno por cada día del horizonte. La función objetivo es el error absoluto (`l1`).

**Detalles de la red:** función de pérdida MAE, optimizador Adam (tasa de aprendizaje 0.001), lotes de 512 ejemplos y semilla fija (42) para que el resultado sea reproducible.

### 6.4 Cómo verificamos que la red no se sobreajustara

La curva de aprendizaje (`ml/notebooks/figuras/v0.1/02_curva_aprendizaje.png`) muestra que el error de validación se mantiene estable (0.127–0.129) mientras baja el de entrenamiento. Si el modelo estuviera memorizando, el error de validación subiría.

### 6.5 Cómo se hizo la prueba en 2017

Con el modelo ya entrenado y **congelado** (sus pesos no cambian más), se simulan las 52 semanas de 2017, una por una, como si fuera uso real:

1. Se toma como corte cada domingo de 2017, del 1 de enero al 24 de diciembre.
2. El modelo recibe las 42 entradas de ese corte. Ejemplo para el **domingo 5 de marzo de 2017**: las ventas del 6 de febrero al 5 de marzo de 2017 y las del 7 al 13 de marzo de 2016.
3. Pronostica de lunes a domingo: del 6 al 12 de marzo de 2017.
4. Se compara con las ventas reales de esos días, que el modelo **nunca vio** durante el entrenamiento.
5. Se repite con los 52 domingos y los 500 productos: 26,000 semanas pronosticadas, o 182,000 días.
6. Con todos esos errores se calculan el MAE, el WAPE, el sesgo y el WAPE semanal (sección 7).

**¿El modelo usa datos de 2017?** Sí, pero solo como **entrada**: las ventas anteriores a cada corte, igual que en la vida real, donde siempre se conoce el pasado. **No aprendió** de 2017: sus pesos se fijaron con 2014–2016. Las respuestas (los 7 días después de cada corte) solo se usan para calcular el error.

Los otros modelos se evaluaron en los mismos 52 cortes, para que la comparación fuera justa.

## 7. Resultados

### Experimento 1: modelos de referencia (4 semanas de diciembre de 2017)

| Modelo | MAE | WAPE | Sesgo | WAPE semanal |
|---|---|---|---|---|
| Chronos | 6.31 | 14.2% | +5.2% | 8.4% |
| AutoETS | 7.05 | 15.9% | +8.3% | 10.9% |
| Naive estacional | 8.74 | 19.7% | +5.1% | 10.1% |
| Promedio 4 semanas | 10.63 | 24.0% | +20.1% | 20.5% |

Chronos gana. Todos se pasan (sesgo positivo) porque en diciembre la venta cae y casi ningún modelo lo anticipa.

### Experimento 2: modelos entrenados (52 semanas de 2017)

| Modelo | MAE | WAPE | Sesgo | WAPE semanal | Tamaño |
|---|---|---|---|---|---|
| **LightGBM** | 6.41 | 10.9% | −0.3% | **5.2%** | 8,861 KB |
| **MLP** | 6.45 | 11.0% | −0.7% | **5.3%** | **20 KB** |
| Chronos | 7.01 | 11.9% | −1.3% | 6.5% | 183,000 KB |
| Naive estacional | 8.84 | 15.0% | −0.1% | 6.5% | 0 |

Lectura:
- Los modelos entrenados reducen el error semanal en ~20% frente a Chronos y al naive.
- LightGBM y la red quedan prácticamente empatados (0.1 puntos de diferencia).
- Al evaluar el año completo, Chronos deja de ser el mejor: diciembre lo favorecía. Por eso hay que evaluar sobre todas las temporadas.

## 8. Por qué elegimos la red neuronal (MLP)

1. Tiene la misma precisión que LightGBM, el mejor modelo.
2. Pesa **440 veces menos** (20 KB frente a 8.9 MB) y cabe en el ESP32-S3.
3. Supera al naive estacional, la condición mínima para justificar un modelo.
4. Usa capas densas, totalmente compatibles con TensorFlow Lite Micro.

## 9. Limitaciones

- **Necesita un año de historial** por producto (por la variable "misma semana del año anterior"). Para productos nuevos se usaría Chronos o el naive.
- Datos limpios: con datos reales habrá productos agotados, que registran 0 ventas aunque haya demanda.
- Solo pronostica la mediana (el valor central), no un rango.
- Hiperparámetros sin ajustar (valores estándar).
- Falta comprobar que la versión int8 mantiene la precisión (notebook 03).

## 10. Preguntas probables del profesor

| Pregunta | Respuesta corta |
|---|---|
| ¿Por qué no usaron solo la red? | Hay que compararla contra algo. Las reglas simples y Chronos sirven de referencia; si la red no les ganara, no tendría sentido usarla. |
| ¿Cómo saben que no hay trampa en la evaluación? | Partición por tiempo, `assert` contra fuga de información, prueba usada una sola vez y control de consistencia entre notebooks (8.74). |
| ¿Por qué WAPE y no precisión (accuracy)? | La accuracy es para clasificación; esto es regresión (números). El WAPE mide el error relativo y no falla con ceros. |
| ¿Chronos no es mejor por ser una IA más grande? | No en este caso: sin entrenar con los datos, pierde en los cambios de temporada. Un modelo pequeño entrenado para el problema le gana. |
| ¿Funciona con datos reales? | La metodología sí se reutiliza; el modelo debe reentrenarse con datos propios y necesita un año de historial. |
| ¿Qué es TinyML? | Ejecutar modelos de machine learning en microcontroladores. Aquí: la red cuantizada a int8 (~5 KB) ejecutándose en el ESP32-S3. |
