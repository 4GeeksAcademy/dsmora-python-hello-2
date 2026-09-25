## Machine Learning

Programación - Determinista 

entrada -> proceso -> salida

def sum(x, y): 
    return x + y

Programación - Probabilistica / Basada en probabilidades 

entrada -> procesa -> predicción 

## DEPENDE 

## Terminos 
## Machine Learning 
## Probabilidad 
## Datos - DataSet 
    - Caracteristicas (timestamp, asunto, remitente, contenido)
    - Etiqueta (resultado de evaluacion en el modelo) importante o no | spam o no
    - 100000 emails 
    - remitente, contenido, hora, etiqueta 

### Ejemplo de dataset: prediccion del precio de una casa

Cada observacion contiene ocho caracteristicas de entrada y una etiqueta de
valor continuo: el precio de la casa en euros.

| Superficie_m2 | Habitaciones | Banos | Fecha_construccion | Distancia_centro_km | Plantas | Tiene_garaje | Tiene_jardin | Precio_euros |
|---:|---:|---:|---:|---:|---:|:---:|:---:|---:|
| 85 | 3 | 1 | 2004-01-15 | 4.5 | 1 | Si | No | 185000.00 |
| 120 | 4 | 2 | 2014-06-20 | 2.0 | 2 | Si | Si | 310500.50 |
| 65 | 2 | 1 | 1989-03-10 | 8.0 | 1 | No | No | 128750.00 |
| 150 | 5 | 3 | 2019-09-05 | 1.2 | 2 | Si | Si | 487900.75 |
| 95 | 3 | 2 | 2009-11-25 | 6.3 | 1 | Si | Si | 242300.00 |
| 210 | 6 | 3 | 2022-02-14 | 0.8 | 3 | Si | Si | 725000.25 |
| 78 | 2 | 1 | 1984-07-01 | 10.5 | 1 | No | No | 99500.00 |
| 110 | 4 | 2 | 2016-04-18 | 3.7 | 2 | Si | No | 278450.80 |
| 135 | 4 | 2 | 2006-08-30 | 5.1 | 2 | Si | Si | 356700.00 |
| 72 | 2 | 1 | 1996-12-12 | 7.4 | 1 | No | Si | 156250.40 |

#### Registros con problemas de calidad

Los siguientes registros se han añadido intencionadamente para practicar la
limpieza de datos. Incluyen duplicados, valores ausentes, incoherencias y
valores negativos.

| Superficie_m2 | Habitaciones | Banos | Fecha_construccion | Distancia_centro_km | Plantas | Tiene_garaje | Tiene_jardin | Precio_euros | Problema |
|---:|---:|---:|---:|---:|---:|:---:|:---:|---:|:---|
| 85 | 3 | 1 | 2004-01-15 | 4.5 | 1 | Si | No | 185000.00 | Duplicado del primer registro |
| 120 | 4 | 2 | 2014-06-20 | 2.0 | 2 | Si | Si | 310500.50 | Duplicado del segundo registro |
| 100 | 3 |  | 2012-05-11 | 3.0 | 2 | Si | No | 265000.00 | Valor ausente en Banos |
|  | 4 | 2 | 2017-10-03 | 2.5 | 2 | Si | Si | 330000.00 | Valor ausente en Superficie_m2 |
| 90 | 0 | 5 | 2018-03-22 | 1.5 | 1 | No | Si | 250000.00 | Incoherencia entre Habitaciones y Banos |
| 70 | 2 | 1 | 2020-02-30 | 5.0 | 1 | No | No | 140000.00 | Fecha de construccion incoherente; corregir antes de cargar |
| -45 | 2 | 1 | 2014-06-20 | 4.0 | 1 | No | No | 100000.00 | Superficie_m2 negativa |
| 80 | 3 | 1 | 2009-11-25 | -2.0 | 1 | Si | No | 190000.00 | Distancia_centro_km negativa |
| 95 | 3 | 2 | 2009-11-25 | 6.3 | 1 | Tal vez | Si | 242300.00 | Valor incoherente en Tiene_garaje |
| 60 | 2 | 1 | 1999-02-08 | 8.0 | 1 | No | No | -50000.00 | Precio_euros negativo |
## EDA (Limpiar y formatear)  Exploratory Data Analysis
## Paradigmas 
    - Aprendizaje supervisado
        - Aquel que tiene un dataset etiquetado 
    - Aprendizaje no supervisado
        - No tiene etiquetas, sirve para agrupar contenidos. 
        - Viene muy bien para segmentar 

    - Aprendizaje auto-supervisado
        - El propio modelo se encarga de etiquetar 
    - Aprendizaje por refuerzo
        - Por refuerzo (recompensas) 
    - Deep Learning (puede combinar los 4 anteriores)
        - Redes neuronales (AI Moderna) 
        - LLM 
        - Capas ponderadas 
## Modelos 
    - Entrenamiento 
    - Pre entrenados
    - Inferencia va ser el proceso de evaluar nuestros valores con el modelo que hayamos elegido. No va a afectar el entrenamiento previo del modelo. 
    - Sobreajuste 
        - entrenamiento acierta 97 % correcto  
        - test acierta solo el 68 % 
## Metricas 

## Redes Neuronales 
- Capa de entrada: recibe los datos en bruto (por ejemplo, los pixeles de una imagen).
- Capas ocultas: transforman la entrada mediante conexiones ponderadas; cada conexion tiene un peso.
- Capa de salida: produce la prediccion o clasificacion final, tras aplicar una funcion de activacion a las entradas ponderadas combinadas.

Cuando usar o no una red neuronal 
Mucha capacidad de computo 
RAM, mucha grafica, mucho computo. 


Netflix 

DEPENDE 