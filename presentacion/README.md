# Presentación (Slidev)

Requiere Node.js 22.12 o superior (`node --version`).

```bash
cd presentacion
npm install          # una vez, CON internet (antes de conectarse a la red de la Raspberry Pi)
npm run dev          # abre la presentación en el navegador (http://localhost:3030)
```

- `slides.md`: el contenido, una diapositiva por bloque separado con `---`.
- `style.css`: colores, tamaños y bloques (`panel`, `grid-2`, `stat`, `steps`...).
- `global-top.vue`: el pie de página con el número de diapositiva.
- `public/fonts/`: Inter y DejaVu Sans Mono, incluidas para que la presentación
  se vea igual sin internet.

En la presentación: flechas para avanzar, `o` para ver todas, `f` pantalla completa.
Exportar a PDF: `npm run export` (necesita `npx playwright install chromium` una vez).
