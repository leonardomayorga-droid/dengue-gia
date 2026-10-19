# Guion del video de presentación

Texto narrado en el video, con el minuto en que inicia cada bloque y el integrante responsable. La narración usa voz sintética.

## 00:00 · Leonardo Mayorga

Somos el equipo de Global Insights Analytics. Un cliente del sector salud nos pidió una respuesta concreta: ¿dónde concentrar los recursos contra el dengue y con cuánta anticipación actuar? El dengue es la arbovirosis de mayor carga en Colombia. Su comportamiento es estacional y ligado al clima, así que la decisión no puede tomarse mirando solo el acumulado del año. El tablero sigue un arco narrativo de seis preguntas: cómo estamos, dónde se concentra, si estamos por encima de lo esperado, qué dice el clima, qué viene y dónde intervenir primero. En 2025 se notificaron 121.543 casos, 229 por cada 100.000 habitantes: 61 % menos que en la epidemia récord de 2024. Pero ojo: el 1,04 % fue dengue grave, el 37,8 % de los casos requirió hospitalización y la letalidad subió a 0,11 %. Menos casos no significa menos riesgo. Además, ocho departamentos crecieron frente a 2024, encabezados por Magdalena, que más que duplicó sus casos, y La Guajira, con 84 % más.

## 01:17 · Dayanis Herrera

Integramos seis fuentes heterogéneas: los microdatos del SIVIGILA en hojas de cálculo, la API de DIVIPOLA, la API histórica de Open-Meteo, su pronóstico en tiempo real, las proyecciones del DANE y, como fuente no estructurada, el texto de los boletines epidemiológicos del INS. Usamos una arquitectura por capas: bronce guarda los datos tal como llegan, plata los limpia y los tipa en Parquet, y oro es el modelo estrella que consume Power BI, también disponible en SQLite. Cargamos 883 mil registros de 2019 a 2025 y aplicamos siete reglas documentadas en esta bitácora. Por ejemplo, excluimos 2.341 casos ocurridos fuera del país y evitamos contar dos veces 86 muertes que aparecían en dos eventos. Al contrastar con el boletín del INS, nuestra cifra de 2025 difiere apenas 1,8 %. En el análisis exploratorio vimos que los casos semanales por municipio son muy asimétricos: mediana de 2, máximo de 1.307. Por eso usamos correlación de Spearman y no de Pearson.

## 02:30 · Angie Atencio

El volumen se concentra en pocos lugares: los diez municipios con más casos, encabezados por Cartagena, Villavicencio, Montería y Cúcuta, aportan el 31 % del total. Pero la incidencia cuenta otra historia: Guaviare tiene 1.150 casos por 100.000 habitantes, cinco veces el promedio nacional, seguido de Arauca y Meta. El mapa es interactivo: al hacer clic en un departamento, toda la página se filtra a ese territorio. Para saber si un número es alto hay que compararlo con lo esperado. Este es el canal endémico: las líneas muestran los cuartiles de los años de referencia y la línea azul, los casos de 2025. En 2025, 21 semanas estuvieron en alerta o epidemia, todas en la primera mitad del año: era la cola de la epidemia de 2024, que llegó a 9.396 casos en una sola semana. El semáforo lo resume semana a semana: rojo y naranja al inicio y verde desde la mitad del año. Hoy estamos por debajo de lo esperado.

## 03:46 · Dayanis Herrera

¿Podemos anticipar la temporada? Entre años, los más cálidos tienen más dengue: 2022 fue el más frío y tuvo 30 mil casos en estos municipios; 2024, con El Niño, casi 179 mil. La correlación es de 0,69 y es positiva en el 93 % de los municipios. Dentro de cada año, la lluvia antecede los casos unas seis semanas, pero con un efecto débil: correlación de 0,15. El segmentador de rezago desplaza la curva de lluvia de cero a doce semanas para explorar esa relación. Conclusión: la temperatura sirve para dimensionar la temporada y la lluvia, como apoyo para el momento. Son asociaciones, no causalidad.

## 04:34 · Angie Atencio

Esta página se alimenta del pronóstico de Open-Meteo consultado el 19 de octubre de 2026. Combinamos la lluvia y la temperatura de las últimas ocho semanas con el pronóstico de 16 días frente a lo normal. Hoy, 3 de 40 municipios tienen señal climática alta: Tumaco, con lluvias 128 % sobre lo normal; Pitalito, 2 grados más cálido; y Popayán.

## 05:02 · Leonardo Mayorga

Integramos todo en un índice de priorización de 0 a 100 que pondera incidencia, carga, severidad, letalidad, tendencia y señal climática. Diez departamentos quedan en prioridad alta, encabezados por Meta, Risaralda, La Guajira, Bolívar y Putumayo. Risaralda y La Guajira no entran por volumen sino por letalidad: más del doble de la nacional.

## 05:26 · Angie Atencio

Lo contrastamos con el texto de los boletines del INS: Meta y Vichada coinciden; Guaviare y Magdalena aparecen en las alertas del INS y quedan para revisión.

## 05:39 · Leonardo Mayorga

Recomendamos tres acciones: uno, control vectorial y búsqueda activa en Meta, Bolívar, Putumayo, Vichada, Cesar, Arauca y Norte de Santander; dos, auditoría de muertes y manejo clínico del dengue grave en Risaralda, La Guajira y Huila; tres, alerta climática en los municipios con señal alta. En síntesis: el dengue no se distribuye ni se mueve igual en todo el país. Mirar incidencia, severidad y clima a la vez permite actuar antes y donde más impacto tiene. Gracias.

Tiempo por integrante: Leonardo Mayorga 2:19 · Dayanis Herrera 2:02 · Angie Atencio 1:55.
