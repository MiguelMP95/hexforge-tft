# Hexforge TFT

Web de composiciones de Teamfight Tactics (Set 18) con estadísticas propias calculadas a partir de partidas de jugadores Master+ de EUW.

- **Composiciones**: tier list con puesto medio, top 4, victorias, objetos de los carries, aumentos y transición early/mid.
- **Creador**: monta tu equipo con campeones y componentes y te recomienda a qué composición ir.

## Actualizar los datos

```sh
echo "RGAPI-..." > .riot_key        # clave de la API de Riot (no se sube al repositorio)
./update_stats.sh                   # descarga partidas nuevas y regenera data/comps.json
python3 scripts/build_data.py       # solo si cambia el parche: campeones, objetos, rasgos e imágenes
```

## Probar en local

```sh
python3 -m http.server 8080
```

Hexforge TFT no está respaldado por Riot Games ni refleja sus opiniones. Teamfight Tactics y sus recursos son marcas de Riot Games, Inc. Datos del juego: Community Dragon.
