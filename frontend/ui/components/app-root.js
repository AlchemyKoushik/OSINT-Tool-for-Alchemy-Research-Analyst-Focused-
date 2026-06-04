export function mountApp(rootElement, createRoot, html, App) {
  if (!rootElement) {
    return;
  }
  createRoot(rootElement).render(html`<${App} />`);
}
