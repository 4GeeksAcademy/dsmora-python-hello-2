import { createRootRoute, HeadContent, Outlet, Scripts } from '@tanstack/react-router'
import '../styles.css'

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: 'Mexico Lindo | Tu proximo viaje' },
    ],
  }),
  component: () => (
    <html lang="es">
      <head><HeadContent /></head>
      <body><Outlet /><Scripts /></body>
    </html>
  ),
  notFoundComponent: () => <main><h1>Pagina no encontrada</h1><a href="/">Volver a Agent</a></main>,
  errorComponent: () => <main role="alert">No se pudo cargar la pagina. <a href="/">Volver a intentar</a></main>,
})
